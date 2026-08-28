# apps/api 진입점 — F-01/F-02/F-05는 mcp-server(rest_server.py)에 위임하는 오케스트레이션
# 레이어이고, F-03(딥보이스)은 이 안에서 직접 판별한다.
#
# 헥사고날 아키텍처 계층 안내:
#   domain/         - 순수 비즈니스 모델 (외부 의존성 없음)
#   application/     - 유스케이스 (domain을 조합, infrastructure는 인터페이스로만 참조)
#   infrastructure/  - FastAPI 라우터, DB, 외부 API 호출 등 "바깥 세상"과의 연결부
#
# main.py는 infrastructure 계층에 해당한다 (프레임워크 진입점이므로).

import os

import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.application.services import (
    AnalyzeCallService,
    CallLogQueryService,
    DeepvoiceDetectionService,
    TranscribeAndAnalyzeCallService,
)
from src.domain.entities import CallAnalysisResult
from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter
from src.infrastructure.adapters.in_memory_call_log import InMemoryCallLogRepository
from src.infrastructure.adapters.mcp_client_adapter import McpServerCallAnalysisAdapter
from src.infrastructure.adapters.stt_client_adapter import SttWorkerTranscriptionAdapter

# F-01/F-02/F-05: mcp-server REST 어댑터 주소. docker-compose로 묶이면 컨테이너 네트워크
# 주소(예: http://mcp-server:8100)로 오버라이드하면 되도록 환경변수로 뺐다.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100")
# F-05: stt-worker REST 어댑터 주소. run-voice-phishing-detector 스킬 기준 로컬 기본 포트는
# 8300 (apps/stt-worker/src/main.py 상단 주석 참고).
STT_WORKER_URL = os.environ.get("STT_WORKER_URL", "http://localhost:8300")

app = FastAPI(title="Voice Phishing Detector API")

# TODO: 프로덕션에서는 origin을 실제 배포된 frontend 도메인으로 제한할 것
# 개발 환경(특히 WSL2 — localhost 포워딩이 불안정해서 브라우저가 WSL IP로 직접 접속하는
# 경우가 있음)에서는 origin이 매번 달라질 수 있어, 로컬 개발 중에는 전부 허용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

call_log_repository = InMemoryCallLogRepository()
analyze_call_service = AnalyzeCallService(
    McpServerCallAnalysisAdapter(MCP_SERVER_URL), call_log_repository
)
transcribe_and_analyze_call_service = TranscribeAndAnalyzeCallService(
    SttWorkerTranscriptionAdapter(STT_WORKER_URL), analyze_call_service
)
call_log_query_service = CallLogQueryService(call_log_repository)
deepvoice_detection_service = DeepvoiceDetectionService(HeuristicDeepvoiceAdapter())


def _serialize_call_result(result: CallAnalysisResult) -> dict:
    return {
        "call_id": result.call_id,
        "analyzed_at": result.analyzed_at.isoformat(),
        "raw_transcript": result.raw_transcript,
        "risk_score": result.risk_score,
        "risk_level": result.risk_level.value,
        "detected_patterns": [
            {
                "category": p.category,
                "category_label": p.category_label,
                "matched_keywords": p.matched_keywords,
            }
            for p in result.detected_patterns
        ],
        "explanation_summary": result.explanation_summary,
        "explanation": result.explanation,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


READY_CHECK_TIMEOUT_SECONDS = 2.0


def _check_mcp_server_ready() -> dict:
    """api의 유일한 실제 의존 서비스(mcp-server)만 확인한다. mcp-server의 얕은
    /health만 호출한다 — mcp-server의 /ready를 부르면 연쇄 호출이 되고, 나중에
    다른 서비스가 늘어날 때 순환 의존이 생길 여지를 만든다.

    postgres/rag-worker는 이 서비스가 실제로 호출하지 않으므로 여기서 "체크"하지
    않는다 — 체크해봤자 항상 통과하거나(호출도 안 하니까) 거짓 실패만 낼 뿐, 실제
    의존관계를 반영하지 못한다. stt-worker는 F-05 오디오 경로에서 실제로 호출하므로
    별도로 _check_stt_worker_ready에서 체크한다.
    """
    try:
        resp = httpx.get(f"{MCP_SERVER_URL}/health", timeout=READY_CHECK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return {"status": "ok", "detail": MCP_SERVER_URL}
    except httpx.HTTPError as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}


def _check_stt_worker_ready() -> dict:
    """stt-worker는 F-05 오디오 경로(/api/v1/calls/analyze-audio)에서만 쓰인다 —
    텍스트 경로(/api/v1/calls/analyze)는 stt-worker 없이도 동작하므로, mcp-server처럼
    503으로 막지 않고 mcp-server의 Ollama 체크(rest_server.py)와 동일하게
    degraded로만 표시한다.
    """
    try:
        resp = httpx.get(f"{STT_WORKER_URL}/health", timeout=READY_CHECK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return {"status": "ok", "detail": STT_WORKER_URL}
    except httpx.HTTPError as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e} — 오디오 업로드 경로만 영향받음"}


@app.get("/ready")
def ready() -> JSONResponse:
    """/health와 달리 실제 의존 서비스 상태를 확인한다. mcp-server가 응답하지 않으면
    F-01/F-02/F-05 전체가 동작할 수 없으므로 이 경우에만 503을 반환한다. stt-worker는
    오디오 경로에만 필요해 다운돼도 503이 아니라 degraded로 표시한다(위
    _check_stt_worker_ready 주석 참고).
    """
    mcp_check = _check_mcp_server_ready()
    stt_check = _check_stt_worker_ready()
    checks = {
        "mcp_server": mcp_check,
        "stt_worker": stt_check,
        # N-01 감사증적을 아직 postgres가 아니라 인메모리로만 쌓고 있다 — 있는 척
        # 체크를 만들지 않고 미구현 상태임을 명시적으로 알린다.
        "database": {
            "status": "not_configured",
            "detail": "postgres 미연동 (인메모리 저장소 사용 중, N-01 참고)",
        },
    }
    if mcp_check["status"] != "ok":
        overall = "error"
    elif stt_check["status"] != "ok":
        overall = "degraded"
    else:
        overall = "ok"
    return JSONResponse(
        content={"status": overall, "checks": checks},
        status_code=200 if overall != "error" else 503,
    )


class AnalyzeCallRequest(BaseModel):
    transcript: str


@app.post("/api/v1/calls/analyze")
async def analyze_call(req: AnalyzeCallRequest) -> dict:
    """F-01/F-02/F-05: mcp-server에 판정을 위임하고 결과를 감사증적(현재는 인메모리)에 적재한다."""
    try:
        result = await analyze_call_service.execute(req.transcript)
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                f"mcp-server({MCP_SERVER_URL}) 연결 실패: {e}. 먼저 mcp-server REST 어댑터를 "
                "실행하세요 (cd apps/mcp-server && source .venv/bin/activate && "
                "uvicorn rest_server:app --app-dir src --port 8100)."
            ),
        ) from e
    return _serialize_call_result(result)


@app.post("/api/v1/calls/analyze-audio")
async def analyze_call_audio(audio: UploadFile) -> dict:
    """F-05: 모바일 앱이 올린 오디오 청크를 stt-worker로 텍스트 변환한 뒤, analyze_call과
    동일한 판정 경로(mcp-server 위임 → 감사증적 적재)를 그대로 탄다.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="빈 오디오 파일입니다.")

    try:
        result = await transcribe_and_analyze_call_service.execute(audio_bytes)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=422,
            detail=f"stt-worker({STT_WORKER_URL}) 오디오 처리 실패: {e}",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                f"stt-worker({STT_WORKER_URL}) 연결 실패: {e}. 먼저 stt-worker를 "
                "실행하세요 (cd apps/stt-worker && source .venv/bin/activate && "
                "uvicorn src.main:app --port 8300)."
            ),
        ) from e
    return _serialize_call_result(result)


@app.get("/api/v1/calls")
async def list_calls(limit: int = 20) -> dict:
    """F-06: 관제 대시보드의 '탐지 현황' 목록에 쓰인다."""
    results = call_log_query_service.list_recent(limit)
    return {"calls": [_serialize_call_result(r) for r in results]}


@app.get("/api/v1/stats/summary")
async def stats_summary() -> dict:
    """F-06: 관제 대시보드의 '위험도 분포/처리 통계'에 쓰인다."""
    stats = call_log_query_service.stats_summary()
    return {
        "total_analyzed": stats.total_analyzed,
        "risk_level_counts": stats.risk_level_counts,
        "category_counts": [
            {
                "category": c.category,
                "category_label": c.category_label,
                "count": c.count,
            }
            for c in stats.category_counts
        ],
    }


@app.post("/api/v1/calls/deepvoice-check")
async def check_deepvoice(audio: UploadFile) -> dict:
    """F-03: 업로드된 통화 음성이 AI 합성 음성인지 판별한다 (v1: 16-bit PCM WAV만 지원).

    v1은 음향 특징 기반 휴리스틱이며, 정확도가 검증된 딥보이스 탐지기가 아니다
    (infrastructure/adapters/deepvoice_adapter.py 상단 주석 참고).
    """
    audio_bytes = await audio.read()
    try:
        verdict = await deepvoice_detection_service.execute(audio_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return {
        "is_synthetic": verdict.is_synthetic,
        "confidence": verdict.confidence,
        "indicators": [
            {"name": i.name, "description": i.description, "triggered": i.triggered}
            for i in verdict.indicators
        ],
        "explanation": verdict.explanation,
    }


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    # TODO: 인증 없이 노출해도 되는지 검토 (내부망 전용이면 OK, 아니면 N-02와 연결)
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# TODO: F-07 신고 접수 엔드포인트 (/api/v1/reports)
# TODO: N-02 RBAC 미들웨어/의존성 추가 (조회/처리/관리자 권한 분리)
