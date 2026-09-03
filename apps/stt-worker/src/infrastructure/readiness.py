# /ready용 순수 함수. main.py에서 분리해둔 이유: main.py를 그냥 import하면
# FasterWhisperAdapter() 생성 시점에 faster-whisper 모델을 실제로 로드한다(GPU
# 워밍업 추론 포함) — 이 파일을 따로 두면 테스트가 main.py 전체를 import하지 않고
# 이 순수 함수만 가짜 서비스로 빠르게 검증할 수 있다
# (apps/stt-worker/tests/test_ready_endpoint.py 참고).

import io
import wave

from src.application.services import TranscribeAudioService


def make_silence_wav_bytes(duration_seconds: float = 0.5, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(b"\x00\x00" * int(sample_rate * duration_seconds))
    return buf.getvalue()


def check_transcription_ready(service: TranscribeAudioService, audio_bytes: bytes, device_info: str) -> dict:
    """/health는 모델 로드 시점의 device/compute_type만 보여준다 — 이 체크는 무음
    오디오로 실제 transcribe() 경로를 다시 태워서, 로드 이후 GPU가 죽는 등의 런타임
    중 고장을 잡는다. 외부 서비스를 호출하지 않으므로 순환 의존 위험이 없다.
    """
    try:
        service.execute(audio_bytes)
        return {"status": "ok", "detail": device_info}
    except Exception as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}
