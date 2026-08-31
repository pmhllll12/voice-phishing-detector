# apps/api 진입점 — F-01/F-02/F-05는 mcp-server(rest_server.py)에 위임하는 오케스트레이션
# 레이어이고, F-03(딥보이스)은 이 안에서 직접 판별한다.
#
# N-02 접근통제: "처리" 행위(analyze_call/analyze-audio/deepvoice-check/reports)는 HANDLER
# 이상, "조회" 행위(list_calls/stats_summary)는 VIEWER 이상 권한을 요구한다 — X-API-Key
# 헤더 기반, infrastructure/adapters/api_key_role_auth.py 참고. health/ready/metrics는
# 인프라 컴포넌트(오케스트레이터, Prometheus)가 호출하고 판정 데이터를 노출하지 않으므로
# 의도적으로 열어둔다(해당 위치 주석 참고).
#
# 헥사고날 아키텍처 계층 안내:
#   domain/         - 순수 비즈니스 모델 (외부 의존성 없음)
#   application/     - 유스케이스 (domain을 조합, infrastructure는 인터페이스로만 참조)
#   infrastructure/  - FastAPI 라우터, DB, 외부 API 호출 등 "바깥 세상"과의 연결부
#
# main.py는 infrastructure 계층에 해당한다 (프레임워크 진입점이므로).

import os
import time

import httpx
import psycopg
from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.application.services import (
    AnalyzeCallService,
    CallLogQueryService,
    DeepvoiceDetectionService,
    ReportSubmissionService,
    TranscribeAndAnalyzeCallService,
)
from src.domain.deepvoice import DeepvoiceVerdict
from src.domain.entities import CallAnalysisResult, Role, role_satisfies
from src.infrastructure.adapters.api_key_role_auth import require_role
from src.infrastructure.adapters.deepvoice_adapter import HeuristicDeepvoiceAdapter
from src.infrastructure.adapters.mcp_client_adapter import McpServerCallAnalysisAdapter
from src.infrastructure.adapters.postgres_call_log_repository import PostgresCallLogRepository
from src.infrastructure.adapters.report_client_adapter import McpServerReportAdapter
from src.infrastructure.adapters.stt_client_adapter import SttWorkerTranscriptionAdapter
from src.infrastructure.metrics import (
    analysis_duration_seconds,
    calls_analyzed_total,
    deepvoice_detected_total,
    reports_submitted_total,
    risk_score_distribution,
)

# F-01/F-02/F-05: mcp-server REST 어댑터 주소. docker-compose로 묶이면 컨테이너 네트워크
# 주소(예: http://mcp-server:8100)로 오버라이드하면 되도록 환경변수로 뺐다.
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8100")
# N-02(2026-08-31): mcp-server 호출용 서비스 자격증명. mcp-server의
# api_key_role_auth.py DEFAULT_API_KEYS와 의도적으로 같은 값(dev-handler-key) —
# 그쪽 모듈 상단 주석 참고. 로컬 개발 전용, 프로덕션에서는 반드시 오버라이드할 것.
MCP_SERVICE_API_KEY = os.environ.get("MCP_SERVICE_API_KEY", "dev-handler-key")
# F-05: stt-worker REST 어댑터 주소. run-voice-phishing-detector 스킬 기준 로컬 기본 포트는
# 8300 (apps/stt-worker/src/main.py 상단 주석 참고).
STT_WORKER_URL = os.environ.get("STT_WORKER_URL", "http://localhost:8300")
# N-01: 감사증적(call_analysis_results) postgres 주소. 로컬 기본값은 docker로 띄운
# vps-postgres 컨테이너 기준(infra/db/init.sql, run-voice-phishing-detector 스킬 참고).
# 프로덕션에서는 반드시 환경변수로 실제 비밀번호를 오버라이드할 것 — 아래 기본값은
# 로컬 개발 전용이다.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)

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

call_log_repository = PostgresCallLogRepository(DATABASE_URL)
analyze_call_service = AnalyzeCallService(
    McpServerCallAnalysisAdapter(MCP_SERVER_URL, MCP_SERVICE_API_KEY), call_log_repository
)
transcribe_and_analyze_call_service = TranscribeAndAnalyzeCallService(
    SttWorkerTranscriptionAdapter(STT_WORKER_URL), analyze_call_service
)
call_log_query_service = CallLogQueryService(call_log_repository)
deepvoice_detection_service = DeepvoiceDetectionService(HeuristicDeepvoiceAdapter())
report_submission_service = ReportSubmissionService(McpServerReportAdapter(MCP_SERVER_URL, MCP_SERVICE_API_KEY))


def _serialize_call_result(result: CallAnalysisResult, role: Role) -> dict:
    # N-03 x N-02: masked_transcript(전화번호/계좌번호/이름 등을 지운 버전)는 누구나 본다.
    # raw_transcript(원문)는 ADMIN 권한에서만 포함한다 — 조회/처리 권한만으로는 원문에
    # 접근할 수 없다(domain/entities.py CallAnalysisResult 상단 주석 참고).
    payload = {
        "call_id": result.call_id,
        "analyzed_at": result.analyzed_at.isoformat(),
        "masked_transcript": result.masked_transcript,
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
        "similar_cases": [
            {
                "case_id": c.case_id,
                "title": c.title,
                "category": c.category,
                "summary": c.summary,
                "source_note": c.source_note,
                "similarity": c.similarity,
            }
            for c in result.similar_cases
        ],
    }
    if role_satisfies(role, Role.ADMIN):
        payload["raw_transcript"] = result.raw_transcript
    return payload


def _record_analysis_metrics(result: CallAnalysisResult, started_at: float) -> None:
    """N-05: 판정이 성공적으로 산출된 경로에서만 기록한다 — mcp-server 연결 실패 등
    에러 경로는 "판정 소요시간"이 아니라 가용성 문제이므로 5초 SLA 계측(vps_analysis_
    duration_seconds)에 섞지 않는다. analyze_call_audio에서는 stt-worker 변환 시간까지
    포함해 측정한다 — N-05가 말하는 "통화 종료 후 판정까지"는 사용자 관점의 전체 응답
    시간이라 STT도 그 안에 들어가야 한다."""
    analysis_duration_seconds.observe(time.monotonic() - started_at)
    calls_analyzed_total.labels(risk_level=result.risk_level.value).inc()
    risk_score_distribution.observe(result.risk_score)


def _record_deepvoice_metrics(verdict: DeepvoiceVerdict) -> None:
    """N-05: is_synthetic이 None(신호 부족으로 판단 보류)이면 "synthetic"도 "authentic"도
    아니므로 기록하지 않는다 — vps_deepvoice_detected_total의 result 라벨은 두 값만
    문서화돼 있다 (infrastructure/metrics.py 참고)."""
    if verdict.is_synthetic is not None:
        deepvoice_detected_total.labels(
            result="synthetic" if verdict.is_synthetic else "authentic"
        ).inc()


# N-02: /health, /ready, /metrics는 의도적으로 인증을 걸지 않는다 — 헬스체크(오케스트레이터/
# 로드밸런서)와 Prometheus 스크레이핑은 API 키를 들고 있지 않은 인프라 컴포넌트가 호출하고,
# 판정 데이터를 노출하지 않으므로(상태값/집계 메트릭뿐) 조회 권한(VIEWER)이 필요한 정보가
# 아니다. 프로덕션에서 이 엔드포인트들을 외부에 노출한다면 내부망/사이드카에서만 접근
# 가능하도록 네트워크 계층에서 막는 편이 API 키보다 적합하다(TODO, N-06/배포 구조와 연결).


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


READY_CHECK_TIMEOUT_SECONDS = 2.0


def _check_mcp_server_ready() -> dict:
    """api의 유일한 실제 의존 서비스(mcp-server)만 확인한다. mcp-server의 얕은
    /health만 호출한다 — mcp-server의 /ready를 부르면 연쇄 호출이 되고, 나중에
    다른 서비스가 늘어날 때 순환 의존이 생길 여지를 만든다.

    rag-worker는 이 서비스가 실제로 호출하지 않으므로 여기서 "체크"하지 않는다 —
    체크해봤자 항상 통과하거나(호출도 안 하니까) 거짓 실패만 낼 뿐, 실제 의존관계를
    반영하지 못한다. postgres는 _check_database_ready에서, stt-worker는
    _check_stt_worker_ready에서 각각 따로 체크한다(둘 다 이 서비스가 실제로 호출함).
    """
    try:
        resp = httpx.get(f"{MCP_SERVER_URL}/health", timeout=READY_CHECK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return {"status": "ok", "detail": MCP_SERVER_URL}
    except httpx.HTTPError as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e}"}


def _check_database_ready() -> dict:
    """N-01 감사증적(call_analysis_results)의 실제 저장소. analyze_call이 매 호출마다
    이 저장소에 쓰기 때문에(AnalyzeCallService.execute), mcp-server와 마찬가지로
    다운되면 503을 반환한다 — degraded로 두면 "판정은 되는데 감사증적이 안 남는" 상태를
    정상처럼 보고하게 되어 N-01 요구사항과 맞지 않는다(stt_worker와 달리 우회 경로가 없음).
    """
    try:
        call_log_repository.ping()
        return {"status": "ok", "detail": "postgres"}
    except psycopg.Error as e:
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
    """/health와 달리 실제 의존 서비스 상태를 확인한다. mcp-server 또는 postgres(N-01
    감사증적)가 응답하지 않으면 analyze_call 자체가 실패하므로 503을 반환한다.
    stt-worker는 오디오 경로에만 필요해 다운돼도 503이 아니라 degraded로 표시한다(위
    _check_stt_worker_ready 주석 참고).
    """
    mcp_check = _check_mcp_server_ready()
    db_check = _check_database_ready()
    stt_check = _check_stt_worker_ready()
    checks = {
        "mcp_server": mcp_check,
        "database": db_check,
        "stt_worker": stt_check,
    }
    if mcp_check["status"] != "ok" or db_check["status"] != "ok":
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
async def analyze_call(req: AnalyzeCallRequest, role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-01/F-02/F-05: mcp-server에 판정을 위임하고 결과를 감사증적(postgres, N-01)에 적재한다.
    N-02: 통화를 분석하는 건 "처리" 행위이므로 HANDLER 이상 권한이 필요하다."""
    started_at = time.monotonic()
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
    _record_analysis_metrics(result, started_at)
    return _serialize_call_result(result, role)


@app.post("/api/v1/calls/analyze-audio")
async def analyze_call_audio(audio: UploadFile, role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-05: 모바일 앱이 올린 오디오 청크를 stt-worker로 텍스트 변환한 뒤, analyze_call과
    동일한 판정 경로(mcp-server 위임 → 감사증적 적재)를 그대로 탄다. N-02: analyze_call과
    동일하게 HANDLER 이상 권한이 필요하다.
    """
    started_at = time.monotonic()
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
    _record_analysis_metrics(result, started_at)
    return _serialize_call_result(result, role)


@app.get("/api/v1/calls")
async def list_calls(limit: int = 20, role: Role = Depends(require_role(Role.VIEWER))) -> dict:
    """F-06: 관제 대시보드의 '탐지 현황' 목록에 쓰인다. N-02: 판정 결과 열람은 VIEWER
    이상이면 충분하다(HANDLER/ADMIN도 role_satisfies 계층 구조상 통과한다)."""
    results = call_log_query_service.list_recent(limit)
    return {"calls": [_serialize_call_result(r, role) for r in results]}


@app.get("/api/v1/stats/summary")
async def stats_summary(_role: Role = Depends(require_role(Role.VIEWER))) -> dict:
    """F-06: 관제 대시보드의 '위험도 분포/처리 통계'에 쓰인다. N-02: list_calls와 동일하게
    VIEWER 이상이면 충분하다."""
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
async def check_deepvoice(audio: UploadFile, _role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-03: 업로드된 통화 음성이 AI 합성 음성인지 판별한다 (v1: 16-bit PCM WAV만 지원).

    v1은 음향 특징 기반 휴리스틱이며, 정확도가 검증된 딥보이스 탐지기가 아니다
    (infrastructure/adapters/deepvoice_adapter.py 상단 주석 참고). N-02: analyze_call과
    동일하게 "처리" 행위라 HANDLER 이상 권한이 필요하다.
    """
    audio_bytes = await audio.read()
    try:
        verdict = await deepvoice_detection_service.execute(audio_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    _record_deepvoice_metrics(verdict)

    return {
        "is_synthetic": verdict.is_synthetic,
        "confidence": verdict.confidence,
        "indicators": [
            {"name": i.name, "description": i.description, "triggered": i.triggered}
            for i in verdict.indicators
        ],
        "explanation": verdict.explanation,
    }


class ReportRequest(BaseModel):
    case_summary: str
    risk_level: str


@app.post("/api/v1/reports")
async def submit_report(req: ReportRequest, _role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-07: 고위험 판정 시 신고 접수(mock)를 mcp-server(submit_report)에 위임한다.
    실제 112/경찰청 신고 API는 호출하지 않는다 (RFP 데이터 제약, docs/RFP.md 4장 참고).
    N-02: 신고 접수도 "처리" 행위라 HANDLER 이상 권한이 필요하다.
    """
    try:
        result = report_submission_service.execute(req.case_summary, req.risk_level)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=422,
            detail=f"mcp-server가 신고 접수 요청을 거부했습니다: {e}",
        ) from e
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                f"mcp-server({MCP_SERVER_URL}) 연결 실패: {e}. 먼저 mcp-server REST 어댑터를 "
                "실행하세요 (cd apps/mcp-server && source .venv/bin/activate && "
                "uvicorn rest_server:app --app-dir src --port 8100)."
            ),
        ) from e
    reports_submitted_total.labels(channel=result["channel"]).inc()
    return result


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
