# /ready는 외부 서비스 없이 실제 transcribe 서비스를 무음 오디오로 1건 호출해
# 자가 점검한다 — src/infrastructure/readiness.py 참고. main.py가 아니라
# readiness.py에서 직접 import하는 이유: main.py를 import하면 FasterWhisperAdapter가
# 실제 faster-whisper 모델을 로드해버려서(GPU 워밍업 추론 포함) 이 테스트가 무겁고
# GPU 의존적으로 바뀐다.

from src.application.services import TranscribeAudioService
from src.domain.entities import TranscriptionResult
from src.infrastructure.readiness import check_transcription_ready, make_silence_wav_bytes


class _WorkingAdapter:
    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        return TranscriptionResult(text="", language="ko", duration_seconds=0.5)


class _BrokenAdapter:
    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        raise RuntimeError("CUDA error: out of memory")


def test_ready_ok_when_transcription_succeeds():
    service = TranscribeAudioService(_WorkingAdapter())

    result = check_transcription_ready(service, make_silence_wav_bytes(), device_info="cpu/int8")

    assert result["status"] == "ok"


def test_ready_error_when_transcription_raises():
    service = TranscribeAudioService(_BrokenAdapter())

    result = check_transcription_ready(service, make_silence_wav_bytes(), device_info="cpu/int8")

    assert result["status"] == "error"
    assert "RuntimeError" in result["detail"]
