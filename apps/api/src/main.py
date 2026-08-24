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
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.application.services import (
    AnalyzeCallService,
    CallLogQueryService,
    DeepvoiceDetectionService,
)
from src.domain.entities import CallAnalysisResult
from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter
from src.infrastructure.adapters.in_memory_call_log import InMemoryCallLogRepository
from src.infrastructure.adapters.mcp_client_adapter import McpServerCallAnalysisAdapter

# F-01/F-02/F-05: mcp-server REST 어댑터 주소. docker-compose로 묶이면 컨테이너 네트워크
# 주소(예: http://mcp-server:8100)로 오버라이드하면 되도록 환경변수로 뺐다.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100")

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
