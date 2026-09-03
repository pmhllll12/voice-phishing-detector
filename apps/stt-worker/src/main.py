# apps/stt-worker 진입점 — 모바일 실시간 감지 파이프라인의 STT(음성 -> 텍스트) API.
#
# 헥사고날 계층 구성: domain(TranscriptionResult, 포트 인터페이스) -> application(유스케이스)
# -> infrastructure(faster-whisper 어댑터, 이 FastAPI 진입점).
#
# 이 서비스는 apps/rag-worker와 같은 이유로 별도 프로세스로 분리했다: RTX 3050 한 장에
# 로컬 GPU 모델(임베딩/LLM/STT)을 여러 개 올려야 하는데, "모델 하나 = 서비스 하나"로
# 나눠야 각 서비스의 GPU 메모리 사용량을 독립적으로 관측(vps_stt_* 등)하고 장애를
# 격리할 수 있다 — mcp-server에 STT를 얹으면 원래 "Ollama에 HTTP만 거는 얇은
# 오케스트레이터"였던 mcp-server에 무거운 GPU 의존성이 섞여버린다.
#
# apps/api가 이 서비스를 호출하는 순서: 모바일 앱 오디오 청크 업로드
#   -> api가 이 서비스(/api/v1/transcribe)를 호출해 텍스트를 받고
#   -> 그 텍스트를 mcp-server(F-01/F-02)에 넘겨 위험도를 판정한다.

import logging

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.application.services import TranscribeAudioService
from src.infrastructure.adapters.faster_whisper_adapter import FasterWhisperAdapter
from src.infrastructure.readiness import check_transcription_ready, make_silence_wav_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Voice Phishing STT Worker")

_stt_adapter = FasterWhisperAdapter()
transcribe_audio_service = TranscribeAudioService(_stt_adapter)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "model": _stt_adapter.model_size,
        "device": _stt_adapter.device,
        "compute_type": _stt_adapter.compute_type,
    }


# 모듈 로드 시 1회만 생성 — /ready가 호출될 때마다 새로 만들 필요 없는 고정 입력.
_READY_CHECK_AUDIO = make_silence_wav_bytes()


@app.get("/ready")
def ready() -> JSONResponse:
    device_info = f"{_stt_adapter.device}/{_stt_adapter.compute_type}"
    check = check_transcription_ready(transcribe_audio_service, _READY_CHECK_AUDIO, device_info)
    status_code = 200 if check["status"] == "ok" else 503
    return JSONResponse(
        content={"status": "ok" if check["status"] == "ok" else "error", "checks": {"transcription": check}},
        status_code=status_code,
    )


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/transcribe")
async def transcribe(audio: UploadFile) -> dict:
    """모바일 앱이 5~10초 단위로 보내는 오디오 청크를 텍스트로 변환한다.

    faster-whisper의 decode_audio(PyAV/ffmpeg 기반)가 컨테이너 포맷을 알아서
    디코딩하므로, wav/m4a/aac 등 흔한 포맷을 그대로 올려도 동작한다.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="빈 오디오 파일입니다.")

    try:
        result = transcribe_audio_service.execute(audio_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"오디오 디코딩/변환 실패: {e}") from e

    return {
        "text": result.text,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
    }


# TODO: 청크 경계에서 문장이 잘리는 문제 — 다음 청크 시작에 이전 청크 끝부분을 약간
#       겹쳐 보내는 방식(overlap)이나, api 쪽에서 최근 N개 청크 텍스트를 이어붙여
#       mcp-server에 넘기는 방식을 검토할 것 (지금은 청크 단위로 완전히 독립 판정).
