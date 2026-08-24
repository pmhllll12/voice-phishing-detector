# F-03 딥보이스(AI 합성 음성) 판별 어댑터 — v1: 음향 특징 기반 휴리스틱.
# domain/ports.py의 DeepvoiceDetectionPort를 구현한다.
#
# WHY 휴리스틱인가 (docs/RFP.md 5장 데이터 제약 참고): 실제 보이스피싱 통화 녹음을 쓸 수
# 없고, 학습된 딥보이스 탐지 모델은 대규모 데이터셋과 GPU가 필요해 이 단계에서 직접 학습시키는
# 것은 비현실적이다. RFP도 "판별 근거를 해석 가능한 형태로 제공하는 것"이 핵심이지 모델을
# 직접 만드는 것 자체가 목표가 아니라고 명시한다. 그래서 v1은 신경망 대신, 공개적으로 알려진
# AI 합성 음성(TTS/보코더)의 특징적 아티팩트 3가지를 직접 계산해 휴리스틱으로 판단한다:
#
#   1. 피치 안정성(jitter) — 일부 신경망 보코더는 프레임 간 피치가 자연 발화보다
#      비정상적으로 안정적인 경향이 있다.
#   2. 스펙트럼 평탄도(spectral flatness)의 구간별 변화 — 자연 발화는 시간에 따라
#      스펙트럼 특성이 미세하게 계속 변하는데, 일부 합성 음성은 이 변화폭이 작다.
#   3. 묵음(pause) 길이의 규칙성 — TTS로 문장을 이어붙인 음성은 묵음 길이가
#      부자연스럽게 균일한 경우가 있다.
#
# ⚠️ 중요한 한계: 위 임계값들은 실제 데이터로 검증되지 않은 초기값이다. 이 어댑터는
# "설명 가능한 판별 인터페이스"를 보여주기 위한 v1이며, 정확도가 검증된 딥보이스
# 탐지기가 아니다. 포트폴리오에서 이 점을 명확히 밝힐 것.
#
# TODO (고도화 순서):
#   1. 실제 음성 샘플(공개 TTS 합성 음성 vs 일반 육성 녹음)로 임계값 보정
#   2. 검증된 오픈소스 스푸핑 탐지 모델(ASVspoof 계열 등)로 교체 검토
#      — DeepvoiceDetectionPort 인터페이스는 그대로 유지
#   3. 현재는 16-bit PCM WAV만 지원 — mp3 등 다른 포맷은 서버 단에서 변환 필요

import io
import wave

import numpy as np

from src.domain.deepvoice import DeepvoiceIndicator, DeepvoiceVerdict

FRAME_SIZE = 1024
HOP_SIZE = 512

SILENCE_ENERGY_RATIO = 0.05  # 프레임 RMS가 (전체 최대 RMS * 이 비율) 이하면 묵음으로 간주
MIN_VOICED_FRAMES = 5  # 이보다 유성음 구간이 적으면 판단 보류

PITCH_MIN_HZ = 80
PITCH_MAX_HZ = 400

# TODO: 아래 3개 임계값 모두 미검증 초기값 — 실제 데이터로 보정 필요
JITTER_LOW_THRESHOLD = 0.01
SPECTRAL_FLATNESS_STD_THRESHOLD = 0.01
PAUSE_CV_THRESHOLD = 0.15
MIN_SILENCE_SEGMENTS = 3


def _read_wav(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            n_channels = wav_file.getnchannels()
            raw = wav_file.readframes(wav_file.getnframes())
    except wave.Error as e:
        raise ValueError(f"WAV 파일을 읽을 수 없습니다: {e}") from e

    if sample_width != 2:
        raise ValueError(
            f"현재는 16-bit PCM WAV만 지원합니다 (입력: {sample_width * 8}-bit). "
            "TODO: 다른 포맷/비트 깊이 지원 추가"
        )

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    return samples, sample_rate


def _frame_signal(samples: np.ndarray, frame_size: int, hop_size: int) -> list[np.ndarray]:
    frames = []
    for start in range(0, len(samples) - frame_size + 1, hop_size):
        frames.append(samples[start : start + frame_size])
    return frames


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))


def _estimate_pitch(frame: np.ndarray, sample_rate: int) -> float | None:
    """자기상관(autocorrelation) 기반 피치 추정. 유효 범위 밖이면 None."""
    centered = frame - np.mean(frame)
    if np.allclose(centered, 0):
        return None

    autocorr = np.correlate(centered, centered, mode="full")
    autocorr = autocorr[len(autocorr) // 2 :]
    if autocorr[0] <= 0:
        return None

    min_lag = int(sample_rate / PITCH_MAX_HZ)
    max_lag = int(sample_rate / PITCH_MIN_HZ)
    if max_lag >= len(autocorr) or min_lag >= max_lag:
        return None

    segment = autocorr[min_lag:max_lag]
    peak_offset = int(np.argmax(segment))
    if segment[peak_offset] <= 0:
        return None

    peak_lag = peak_offset + min_lag
    return sample_rate / peak_lag


def _spectral_flatness(frame: np.ndarray) -> float:
    """Wiener entropy: 스펙트럼 파워의 기하평균/산술평균. 0에 가까울수록 톤(harmonic)적,
    1에 가까울수록 백색소음에 가깝다. 여기서는 절대값보다 '구간별 변화폭'에 관심이 있다."""
    windowed = frame * np.hanning(len(frame))
    power = np.abs(np.fft.rfft(windowed)) ** 2 + 1e-12
    geometric_mean = np.exp(np.mean(np.log(power)))
    arithmetic_mean = np.mean(power)
    return float(geometric_mean / arithmetic_mean)


class HeuristicDeepvoiceAdapter:
    def analyze(self, audio_bytes: bytes) -> DeepvoiceVerdict:
        samples, sample_rate = _read_wav(audio_bytes)
        frames = _frame_signal(samples, FRAME_SIZE, HOP_SIZE)

        if not frames:
            return DeepvoiceVerdict(
                is_synthetic=None,
                confidence=0.0,
                indicators=[],
                explanation="오디오 길이가 너무 짧아 판단할 수 없습니다.",
            )

        rms_values = [_rms(f) for f in frames]
        silence_threshold = max(rms_values, default=0.0) * SILENCE_ENERGY_RATIO
        voiced_indices = [i for i, r in enumerate(rms_values) if r > silence_threshold]

        pitch_indicator = self._pitch_stability_indicator(frames, voiced_indices, sample_rate)
        spectral_indicator = self._spectral_uniformity_indicator(frames, voiced_indices)
        pause_indicator = self._pause_regularity_indicator(rms_values, silence_threshold, sample_rate)
        indicators = [pitch_indicator, spectral_indicator, pause_indicator]

        if len(voiced_indices) < MIN_VOICED_FRAMES:
            return DeepvoiceVerdict(
                is_synthetic=None,
                confidence=0.0,
                indicators=indicators,
                explanation="유효한 음성 구간이 너무 짧아 판단을 보류합니다 (묵음이 대부분이거나 신호가 약함).",
            )

        triggered = [i for i in indicators if i.triggered]

        if len(triggered) >= 2:
            is_synthetic: bool | None = True
            confidence = min(0.5 + 0.15 * len(triggered), 0.9)
            verdict_sentence = "AI 합성 음성(딥보이스)일 가능성이 있습니다."
        elif len(triggered) == 1:
            is_synthetic = None
            confidence = 0.4
            verdict_sentence = "일부 의심 정황이 있으나 단정하기엔 근거가 부족해 추가 검토가 필요합니다."
        else:
            is_synthetic = False
            confidence = 0.7
            verdict_sentence = "뚜렷한 합성 음성 정황이 발견되지 않았습니다."

        return DeepvoiceVerdict(
            is_synthetic=is_synthetic,
            confidence=confidence,
            indicators=indicators,
            explanation=self._build_explanation(verdict_sentence, indicators),
        )

    def _pitch_stability_indicator(
        self, frames: list[np.ndarray], voiced_indices: list[int], sample_rate: int
    ) -> DeepvoiceIndicator:
        pitches = [p for i in voiced_indices if (p := _estimate_pitch(frames[i], sample_rate))]

        if len(pitches) < 3:
            return DeepvoiceIndicator(
                name="pitch_stability",
                description="피치를 추정할 수 있는 유성음 구간이 부족해 평가하지 않았습니다.",
                triggered=False,
            )

        diffs = [abs(pitches[i] - pitches[i - 1]) for i in range(1, len(pitches))]
        mean_pitch = sum(pitches) / len(pitches)
        jitter = (sum(diffs) / len(diffs)) / mean_pitch if mean_pitch else 0.0
        triggered = jitter < JITTER_LOW_THRESHOLD

        return DeepvoiceIndicator(
            name="pitch_stability",
            description=(
                f"프레임 간 피치 변동률(jitter)이 {jitter:.4f}로 "
                f"{'자연 발화 대비 비정상적으로 안정적입니다' if triggered else '자연스러운 변동 범위입니다'} "
                f"(기준치 {JITTER_LOW_THRESHOLD})."
            ),
            triggered=triggered,
        )

    def _spectral_uniformity_indicator(
        self, frames: list[np.ndarray], voiced_indices: list[int]
    ) -> DeepvoiceIndicator:
        flatness_values = [_spectral_flatness(frames[i]) for i in voiced_indices]

        if len(flatness_values) < 3:
            return DeepvoiceIndicator(
                name="spectral_uniformity",
                description="스펙트럼을 평가할 유성음 구간이 부족해 평가하지 않았습니다.",
                triggered=False,
            )

        std = float(np.std(flatness_values))
        triggered = std < SPECTRAL_FLATNESS_STD_THRESHOLD

        return DeepvoiceIndicator(
            name="spectral_uniformity",
            description=(
                f"구간별 스펙트럼 평탄도의 표준편차가 {std:.5f}로 "
                f"{'프레임 간 변화가 비정상적으로 적습니다' if triggered else '자연스러운 변화폭을 보입니다'} "
                f"(기준치 {SPECTRAL_FLATNESS_STD_THRESHOLD})."
            ),
            triggered=triggered,
        )

    def _pause_regularity_indicator(
        self, rms_values: list[float], silence_threshold: float, sample_rate: int
    ) -> DeepvoiceIndicator:
        frame_duration = HOP_SIZE / sample_rate
        durations: list[float] = []
        current_run = 0
        for r in rms_values:
            if r <= silence_threshold:
                current_run += 1
            else:
                if current_run > 0:
                    durations.append(current_run * frame_duration)
                current_run = 0
        if current_run > 0:
            durations.append(current_run * frame_duration)

        if len(durations) < MIN_SILENCE_SEGMENTS:
            return DeepvoiceIndicator(
                name="pause_regularity",
                description=f"묵음 구간이 {len(durations)}개로 적어 평가하지 않았습니다 (최소 {MIN_SILENCE_SEGMENTS}개 필요).",
                triggered=False,
            )

        mean_duration = sum(durations) / len(durations)
        variance = sum((d - mean_duration) ** 2 for d in durations) / len(durations)
        cv = (variance**0.5) / mean_duration if mean_duration else 0.0
        triggered = cv < PAUSE_CV_THRESHOLD

        return DeepvoiceIndicator(
            name="pause_regularity",
            description=(
                f"묵음 구간 {len(durations)}개의 길이 변동계수(CV)가 {cv:.3f}로 "
                f"{'부자연스럽게 규칙적입니다' if triggered else '자연스러운 변동을 보입니다'} "
                f"(기준치 {PAUSE_CV_THRESHOLD})."
            ),
            triggered=triggered,
        )

    @staticmethod
    def _build_explanation(verdict_sentence: str, indicators: list[DeepvoiceIndicator]) -> str:
        lines = [verdict_sentence, "", "지표:"]
        for indicator in indicators:
            mark = "[!]" if indicator.triggered else "[-]"
            lines.append(f"{mark} {indicator.name}: {indicator.description}")
        return "\n".join(lines)
