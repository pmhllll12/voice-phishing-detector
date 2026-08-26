# 모바일 실시간 감지 파이프라인의 STT 구현체: faster-whisper(CTranslate2 기반)로 오디오를
# 텍스트로 변환한다. domain/ports.py의 SpeechToTextPort를 구현한다.
#
# WHY faster-whisper인가: openai-whisper(torch 기반) 대신 CTranslate2 기반의 faster-whisper를
# 골랐다. 같은 정확도 기준으로 추론이 더 빠르고, int8/float16 양자화를 기본 지원해서 VRAM을
# 덜 쓴다 — 이미 임베딩(rag-worker)과 로컬 LLM(mcp-server가 호출하는 Ollama)이 GPU를 나눠
# 쓰고 있는 이 프로젝트 사정에 맞다(자세한 실측치는 프로젝트 README "GPU 자원 사용" 참고).
#
# WHY 'small' 모델 + int8_float16인가: RTX 3050(8GB)에 이미 임베딩(~430MB)과 로컬 LLM
# (EXAONE 3.5, ~1.87GB)이 상시 로드돼 있어 남는 VRAM이 넉넉하지 않다. 실측 결과 둘 다 뜬
# 상태(약 3.9GB 사용 중)에서 'small' + int8_float16을 추가로 로드해도 약 334MB만 더 써서
# 총 사용량 약 4.26GB, 여유 VRAM 약 3.8GB를 유지했다. 정확도가 더 필요하면 STT_MODEL
# 환경변수로 'medium' 등으로 올릴 수 있다(다만 VRAM 재측정 필요).
#
# WHY 자동 CPU 폴백인가: mcp-server의 Ollama 어댑터와 같은 이유 — GPU가 없거나 CUDA 로드에
# 실패해도 STT 자체가 죽어서는 안 된다("판정 불가"보다 느려도 동작하는 게 낫다는 이 프로젝트의
# 일관된 원칙, ollama_call_analysis_adapter.py 참고).

import io
import logging
import os
import time

import numpy as np
from faster_whisper import WhisperModel

from src.domain.entities import TranscriptionResult
from src.infrastructure import metrics

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "small"
DEFAULT_COMPUTE_TYPE = "int8_float16"

# F-01의 통화/문자가 전부 한국어 시나리오라서, 언어 자동 감지(짧은 청크에서는 특히
# 부정확해지기 쉬움) 대신 한국어로 강제 고정한다 — 다국어 지원이 필요해지면 여기를
# 요청 파라미터로 바꾸면 된다.
LANGUAGE = "ko"


def _load_and_warm_up(model_size: str, device: str, compute_type: str) -> WhisperModel:
    """모델을 로드하고, 무음 버퍼로 실제 추론 경로(GPU 커널 포함)까지 태워본다.

    WhisperModel() 생성자는 device="cuda"여도 가중치 로딩만 성공하면 예외 없이
    끝난다 — 실제 인코더/디코더 행렬곱에 쓰이는 cuBLAS 같은 라이브러리가 없으면
    생성자가 아니라 이후 transcribe() 호출에서야 처음 실패한다(로컬에서 실제로
    겪음: libcublas.so.12 not found, 생성자는 통과했었음). device 폴백 여부를
    정확히 판단하려면 생성 시점에 한 번 실제로 태워봐야 한다.
    """
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    silence = np.zeros(16000, dtype=np.float32)  # 16kHz 무음 1초
    segments, _ = model.transcribe(silence, language=LANGUAGE)
    list(segments)  # generator라 소비해야 실제로 인코더/디코더가 실행된다
    return model


class FasterWhisperAdapter:
    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        self.model_size = model_size or os.environ.get("STT_MODEL", DEFAULT_MODEL)
        requested_device = device or os.environ.get("STT_DEVICE", "cuda")
        requested_compute_type = compute_type or os.environ.get(
            "STT_COMPUTE_TYPE", DEFAULT_COMPUTE_TYPE
        )

        gpu_before = metrics.read_total_gpu_memory_used() if requested_device == "cuda" else None
        load_start = time.perf_counter()
        try:
            self._model = _load_and_warm_up(
                self.model_size, requested_device, requested_compute_type
            )
            self.device = requested_device
            self.compute_type = requested_compute_type
        except Exception as e:
            logger.warning(
                "STT 모델을 %s(%s)로 로드/워밍업 실패 — CPU(int8)로 폴백: %s: %s",
                requested_device,
                requested_compute_type,
                type(e).__name__,
                e,
            )
            self.device = "cpu"
            self.compute_type = "int8"
            self._model = _load_and_warm_up(self.model_size, "cpu", "int8")
        load_seconds = time.perf_counter() - load_start

        gpu_delta = 0
        if self.device == "cuda" and gpu_before is not None:
            gpu_after = metrics.read_total_gpu_memory_used()
            if gpu_after is not None:
                gpu_delta = max(0, gpu_after - gpu_before)

        metrics.model_load_duration_seconds.set(load_seconds)
        metrics.gpu_memory_delta_bytes.set(gpu_delta)
        metrics.stt_model_info.info(
            {"model_name": self.model_size, "device": self.device, "compute_type": self.compute_type}
        )
        logger.info(
            "STT model loaded: model=%s device=%s compute_type=%s load_seconds=%.2f gpu_delta_mb=%.1f",
            self.model_size,
            self.device,
            self.compute_type,
            load_seconds,
            gpu_delta / 1e6,
        )

    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        try:
            with metrics.inference_duration_seconds.time():
                segments, info = self._model.transcribe(io.BytesIO(audio_bytes), language=LANGUAGE)
                text = "".join(segment.text for segment in segments)
            metrics.transcription_requests_total.labels(result="success").inc()
            return TranscriptionResult(
                text=text.strip(), language=info.language, duration_seconds=info.duration
            )
        except Exception:
            metrics.transcription_requests_total.labels(result="error").inc()
            raise
