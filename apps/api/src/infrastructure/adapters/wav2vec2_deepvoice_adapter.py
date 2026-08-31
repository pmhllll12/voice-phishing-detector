# F-03 딥보이스(AI 합성 음성) 판별 어댑터 — v2: 검증된 오픈소스 스푸핑 탐지 모델
# (wav2vec2 기반). domain/ports.py의 DeepvoiceDetectionPort를 구현한다 — v1
# (HeuristicDeepvoiceAdapter)과 인터페이스가 완전히 동일해, N-06(확장성) 표(docs/design.md)의
# 4번째 실증 축이다: application 계층(DeepvoiceDetectionService)은 이 교체로 0줄도
# 바뀌지 않았다.
#
# WHY 모델 선택: RFP(docs/RFP.md 4장)는 "딥보이스 판별 모델은 자체 개발 또는 검증된
# 오픈소스 모델 활용 모두 허용한다"고 명시한다 — 평가 기준은 정확도 그 자체가 아니라
# "판별 근거를 해석 가능한 형태로 제공하는 것"이다. 그래서 처음부터 학습시키지 않고
# HuggingFace Hub에서 공개된 오디오 스푸핑 탐지 모델 두 개를 실제 F-03 데이터셋
# (data/deepvoice_samples/, TTS 8건 + 자연 발화 8건)으로 직접 붙여 실측 비교했다:
#
#   - Bisher/wav2vec2_ASV_deepfake_audio_detection (ASVspoof 계열로 추정) — 재현율
#     3/8(37.5%), 오탐 0/8. ASVspoof는 영어 TTS/보코더 스푸핑 위주라, 한국어 gTTS
#     합성 음성에는 잘 일반화되지 않았다.
#   - mo-thecreator/Deepfake-audio-detection (wav2vec2-base 파인튜닝) — 재현율 8/8,
#     오탐 0/8, 전 샘플에서 신뢰도 0.99 이상으로 완전히 분리됨.
#
# 실측 결과 두 번째 모델을 채택했다. 다만 **16건짜리 소규모 데이터셋에서의 완전 분리가
# 일반화를 보장하지 않는다** — v1 상단 주석이 반복해서 강조하는 것과 동일한 한계다.
# 모델 카드에 학습 데이터셋이 명시돼 있지 않아("None"), 우리 데이터셋(gTTS)과 겹칠
# 가능성도 배제할 수 없다. 그래서 v1의 3개 음향 지표는 버리지 않고 "보조 지표"로
# 계속 계산해 함께 반환한다 — N-04(설명가능성)를 "모델이 그렇다고 했다"는 한 줄로
# 끝내지 않고, 사람이 직접 확인 가능한 근거를 여전히 덧붙이기 위함이다.
#
# WHY CPU (device 강제 아님, 하지만 기본값): 이 프로젝트는 이미 같은 GPU(RTX 3050,
# 8GB)에 mcp-server(Ollama LLM)와 rag-worker(임베딩 모델)를 상시 로드해두고 있다
# (ollama_call_analysis_adapter.py 상단 주석 참고). 94.6M 파라미터 wav2vec2-base는
# CPU로도 통화 하나 분량(수 초) 추론이 충분히 빠르고, F-03은 상시 트래픽이 아니라
# 요청 시에만 호출되므로, 세 번째 프로세스가 같은 GPU를 두고 경쟁하게 만들 이유가 없다.
#
# WHY 폴백이 필요한가 (Ollama 폴백과 동일한 이유): 최초 실행 시 HuggingFace Hub에서
# 모델을 받아야 하므로 네트워크가 없거나, 라벨 체계를 알 수 없는 모델로 잘못
# 설정되면 판별 자체가 불가능해진다. 이럴 때 판정이 아예 실패하는 대신 v1(휴리스틱)로
# 안전하게 넘어간다.

import io
import logging
import wave

import numpy as np

from src.domain.deepvoice import DeepvoiceIndicator, DeepvoiceVerdict
from src.domain.ports import DeepvoiceDetectionPort
from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "mo-thecreator/Deepfake-audio-detection"
TARGET_SAMPLE_RATE = 16000

# 라벨 문자열이 모델마다 다를 수 있어(예: "fake"/"real" vs "spoof"/"bonafide") 키워드로
# 느슨하게 매칭한다. 어느 쪽에도 걸리지 않는 라벨(예: "LABEL_0")이면 의미를 알 수 없으므로
# 안전하게 폴백한다 — "블랙박스 라벨을 임의로 해석"하지 않기 위함.
SYNTHETIC_LABEL_KEYWORDS = ("fake", "spoof", "synthetic", "ai", "generated", "tts")
AUTHENTIC_LABEL_KEYWORDS = ("real", "bonafide", "genuine", "human", "natural", "authentic")


def _read_wav_16k_mono(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    """v1(deepvoice_adapter._read_wav)과 동일한 16-bit PCM WAV 파싱을 재사용한 뒤,
    모델이 요구하는 16kHz로 필요 시 리샘플링한다."""
    from src.infrastructure.adapters.deepvoice_adapter import _read_wav  # noqa: PLC0415

    samples, sample_rate = _read_wav(audio_bytes)
    if sample_rate != TARGET_SAMPLE_RATE:
        # 정밀한 리샘플러(scipy 등) 없이도 충분한 선형 보간 — 새 의존성을 늘리지
        # 않기 위한 의도적 선택. 통화 음성 대역(80~400Hz 피치)에서는 근사 리샘플링으로도
        # 분류 모델 입력 품질에 실질적 영향이 없다.
        duration = len(samples) / sample_rate
        target_len = int(duration * TARGET_SAMPLE_RATE)
        original_x = np.linspace(0, duration, num=len(samples), endpoint=False)
        target_x = np.linspace(0, duration, num=target_len, endpoint=False)
        samples = np.interp(target_x, original_x, samples).astype(np.float32)
        sample_rate = TARGET_SAMPLE_RATE
    return samples, sample_rate


class Wav2Vec2DeepvoiceAdapter:
    """F-03 v2. 생성자에서 모델 로드를 시도하고, 실패하면(네트워크 없음 등) analyze()가
    항상 fallback으로 넘어간다. 라벨 의미를 알 수 없는 모델이 설정된 경우도 동일하게
    처리한다 — 둘 다 "이 모델을 신뢰할 수 없다"는 같은 종류의 실패로 취급한다."""

    def __init__(
        self,
        fallback: DeepvoiceDetectionPort,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self._fallback = fallback
        self._model_name = model_name
        self._pipeline = None
        self._synthetic_label: str | None = None
        self._authentic_label: str | None = None

        try:
            self._load_pipeline()
        except Exception as e:  # noqa: BLE001 — 모델 로드 실패 사유가 다양해 폭넓게 잡고 폴백
            logger.warning(
                "wav2vec2 딥보이스 모델(%s) 로드 실패, v1 휴리스틱으로 폴백: %s",
                model_name,
                e,
            )

    def _load_pipeline(self) -> None:
        from transformers import pipeline  # noqa: PLC0415 — torch/transformers는 F-03에만 필요한 무거운 의존성이라 지연 임포트

        self._pipeline = pipeline("audio-classification", model=self._model_name, device="cpu")

        id2label: dict[int, str] = self._pipeline.model.config.id2label
        synthetic = next(
            (v for v in id2label.values() if any(k in v.lower() for k in SYNTHETIC_LABEL_KEYWORDS)),
            None,
        )
        authentic = next(
            (v for v in id2label.values() if any(k in v.lower() for k in AUTHENTIC_LABEL_KEYWORDS)),
            None,
        )
        if synthetic is None or authentic is None:
            self._pipeline = None
            raise ValueError(
                f"모델 라벨({list(id2label.values())})의 의미(합성/실제)를 키워드로 판별할 수 없습니다."
            )
        self._synthetic_label = synthetic
        self._authentic_label = authentic
        logger.info(
            "wav2vec2 딥보이스 모델 로드 완료: model=%s synthetic_label=%s authentic_label=%s",
            self._model_name,
            synthetic,
            authentic,
        )

    def analyze(self, audio_bytes: bytes) -> DeepvoiceVerdict:
        if self._pipeline is None:
            return self._fallback.analyze(audio_bytes)

        try:
            samples, sample_rate = _read_wav_16k_mono(audio_bytes)
            if len(samples) == 0:
                return DeepvoiceVerdict(
                    is_synthetic=None,
                    confidence=0.0,
                    indicators=[],
                    explanation="오디오 길이가 너무 짧아 판단할 수 없습니다.",
                )
            results = self._pipeline({"array": samples, "sampling_rate": sample_rate})
        except Exception as e:  # noqa: BLE001 — 추론 실패도 판정 불가가 아니라 v1로 안전 폴백
            logger.warning("wav2vec2 딥보이스 추론 실패, v1 휴리스틱으로 폴백: %s", e)
            return self._fallback.analyze(audio_bytes)

        top = max(results, key=lambda r: r["score"])
        is_synthetic = top["label"] == self._synthetic_label
        confidence = float(top["score"])

        model_indicator = DeepvoiceIndicator(
            name="wav2vec2_spoof_classifier",
            description=(
                f"딥러닝 스푸핑 탐지 모델({self._model_name})이 "
                f"'{'합성 음성' if is_synthetic else '실제 음성'}'으로 분류했습니다 "
                f"(신뢰도 {confidence:.2%})."
            ),
            triggered=is_synthetic,
        )

        # N-04: 모델 판정 하나로 끝내지 않고, v1의 해석 가능한 음향 지표 3개를 보조
        # 근거로 함께 반환한다 — 모델이 틀렸을 가능성을 사람이 직접 대조 확인할 수 있게.
        supplementary = self._fallback.analyze(audio_bytes).indicators

        explanation_lines = [
            f"AI 합성 음성(딥보이스)일 가능성이 {'높습니다' if is_synthetic else '낮습니다'} "
            f"(딥러닝 모델 신뢰도 {confidence:.2%}).",
            "",
            "판정 근거:",
            f"[{'!' if is_synthetic else '-'}] {model_indicator.description}",
        ]
        for indicator in supplementary:
            mark = "[!]" if indicator.triggered else "[-]"
            explanation_lines.append(f"{mark} (보조 음향 지표) {indicator.description}")

        return DeepvoiceVerdict(
            is_synthetic=is_synthetic,
            confidence=confidence,
            indicators=[model_indicator, *supplementary],
            explanation="\n".join(explanation_lines),
        )
