# apps/mcp-server REST 어댑터 — docker-compose 네트워크에서 apps/api가 호출하는 일반
# HTTP 엔드포인트. server.py(MCP stdio, Claude Code 전용)와 완전히 같은 application
# 서비스를 재사용한다 — 판정 로직은 application/services.py 한 곳에만 있고, 두 어댑터는
# 그걸 감싸는 방식만 다르다.
#
# 실행: uvicorn rest_server:app --app-dir src --port 8100 (apps/mcp-server에서 실행)
# --app-dir src 덕분에 sys.path 루트가 apps/mcp-server/src가 되어, server.py와 동일하게
# "domain.xxx"/"application.xxx" 방식의 import가 그대로 통한다 (apps/api·apps/rag-worker의
# "src.xxx" 방식과는 다름 — 이유는 server.py 상단 주석 참고).
#
# N-02 접근통제(2026-08-31, apps/api에서 이 서비스까지 확장): docker-compose가 8100
# 포트를 직접 노출하므로 apps/api를 거치지 않고 이 REST 어댑터를 바로 호출할 수 있다 —
# 그래서 apps/api와 동일한 X-API-Key 기반 RBAC을 여기에도 적용한다
# (infrastructure/adapters/api_key_role_auth.py 참고). apps/api는 서비스 대 서비스
# 호출로 이 인증을 통과한다(mcp_client_adapter.py/report_client_adapter.py가
# MCP_SERVICE_API_KEY를 보냄). MCP stdio(server.py)는 이 인증 대상이 아니다 — 그쪽
# 상단 주석 참고.

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
import psycopg
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from application.dto import serialize_analysis, serialize_correlation, serialize_report
from application.services import CallAnalysisService, MultichannelCorrelationService, ReportSubmissionService
from domain.entities import Channel, EntityType, ExtractedEntity, Role, RiskLevel
from domain.entity_extraction import extract_entities
from infrastructure.adapters.api_key_role_auth import require_role
from infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from infrastructure.adapters.ollama_call_analysis_adapter import (
    OllamaCallAnalysisAdapter,
    _resolve_base_url,
)
from infrastructure.adapters.postgres_channel_signal_repository import PostgresChannelSignalRepository
from infrastructure.adapters.postgres_report_repository import PostgresReportRepository
from infrastructure.adapters.rag_worker_search_adapter import RagWorkerSearchAdapter
from infrastructure.adapters.rule_based_call_analysis_adapter import RuleBasedCallAnalysisAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Voice Phishing MCP Server (REST adapter)")

# server.py(MCP stdio)와 같은 배선 규칙 — 프로세스가 분리되어 있어(각자 uvicorn/stdio로
# 독립 실행) 코드를 그대로 복붙했다. 공유 모듈로 뽑을 만큼 커지면 그때 리팩터링.
_rule_based_adapter = RuleBasedCallAnalysisAdapter()
_ollama_adapter = OllamaCallAnalysisAdapter(fallback=_rule_based_adapter)

if os.environ.get("CALL_ANALYSIS_BACKEND", "llm").lower() == "rule":
    _call_analysis_adapter = _rule_based_adapter
elif os.environ.get("LLM_DEBUG_COMPARE", "").lower() in ("1", "true", "yes"):
    _call_analysis_adapter = DebugCompareAdapter(_ollama_adapter, _rule_based_adapter)
else:
    _call_analysis_adapter = _ollama_adapter

# F-04: server.py와 동일한 근거로 환경변수로 뺐다 (rest_server.py 상단 주석 참고).
RAG_WORKER_URL = os.environ.get("RAG_WORKER_URL", "http://localhost:8200")
# N-01: 감사증적(report_records) postgres 주소 — apps/api/src/main.py와 동일한 기본값
# (로컬 개발 전용, infra/db/init.sql 참고).
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)

_channel_signal_repository = PostgresChannelSignalRepository(DATABASE_URL)
correlation_service = MultichannelCorrelationService(_channel_signal_repository)

call_analysis_service = CallAnalysisService(
    _call_analysis_adapter, RagWorkerSearchAdapter(RAG_WORKER_URL), correlation_service
)
_report_repository = PostgresReportRepository(DATABASE_URL)
report_submission_service = ReportSubmissionService(_report_repository)

# N-05 동시성 SLA 대응(2026-09-01, 실측 근거는 docs/test-plan.md N-05 절):
# CallAnalysisService.execute()는 동기 코드(httpx.post로 Ollama/rag-worker를 블로킹
# 호출)라, 이 async 핸들러 안에서 그냥 직접 부르면 요청 하나가 끝날 때까지 이벤트
# 루프 전체가 막힌다 — 즉 동시 요청이 몇 개 오든 이 프로세스 안에서는 우발적으로
# 한 번에 하나씩만 처리된다(의도한 직렬화가 아니라 사고에 가깝다).
#
# 고친 방식: run_in_threadpool로 스레드풀에 위임해 이벤트 루프를 막지 않게 했다.
# asyncio.Semaphore로 동시 실행 개수를 명시적으로도 제한한다(무제한 스레드풀
# 위임만 하면 스레드 수만큼 GPU에 요청이 몰릴 수 있어서).
#
# 실측 결과(중요, 정직하게 밝힘): 이 수정은 p95를 18.86초 → 11~13초대로
# 줄였다(동시성 4, LLM_MAX_CONCURRENCY 1/2/4 전부 비슷하게 개선 — 즉 세마포어
# 값 자체는 이 구간에서 결과를 거의 안 바꿨다). **하지만 평균 지연시간(약
# 8.1~8.3초)과 SLA(5초) 위반 비율(96~99%)은 거의 그대로다.** 즉 이 수정은
# "우발적 전체 직렬화로 인한 꼬리 지연(worst-case)"은 줄였지만, "GPU 1장을
# 여러 요청이 실제로 나눠 쓰면서 생기는 평균적인 처리시간 증가"는 못 고친다 —
# 이건 소프트웨어 버그가 아니라 인프라 용량(GPU 처리량) 문제이기 때문이다
# (`docs/design.md` 6장 결론과 일치). LLM_MAX_CONCURRENCY 값 자체(1/2/4)는
# 실측상 거의 차이가 없었다 — 2를 기본값으로 둔 건 그중 근소하게 나은 실측치
# 때문이지, 최적값을 확정했다는 뜻은 아니다. 진짜 SLA 충족은 GPU 용량 확충이나
# 수요 측 제어(요청 큐잉/속도 제한)가 필요하다 — 아직 미도입(`docs/test-plan.md`
# N-05 절 "알려진 커버리지 공백" 참고).
LLM_MAX_CONCURRENCY = int(os.environ.get("LLM_MAX_CONCURRENCY", "2"))
_llm_semaphore = asyncio.Semaphore(LLM_MAX_CONCURRENCY)


# N-02: /health, /ready, /metrics는 apps/api와 동일한 이유로 인증을 걸지 않는다 —
# 인프라 컴포넌트(오케스트레이터, Prometheus)가 호출하고 판정 데이터를 노출하지 않는다
# (apps/api/src/main.py의 동일 주석 참고).


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


READY_CHECK_TIMEOUT_SECONDS = 2.0
_OLLAMA_BACKEND_ACTIVE = os.environ.get("CALL_ANALYSIS_BACKEND", "llm").lower() != "rule"


def _check_ollama_ready() -> dict:
    """CALL_ANALYSIS_BACKEND=rule이면 이 프로세스는 Ollama를 아예 쓰지 않으므로
    체크 대상이 아니다(LLM_DEBUG_COMPARE 모드에서는 실제 응답이 여전히 Ollama
    결과이므로 이 경우엔 체크한다 — 위 _OLLAMA_BACKEND_ACTIVE 조건과 rest_server.py
    상단의 어댑터 선택 로직이 동일 조건을 쓴다).
    """
    if not _OLLAMA_BACKEND_ACTIVE:
        return {"status": "not_applicable", "detail": "CALL_ANALYSIS_BACKEND=rule (Ollama 미사용)"}

    base_url = _resolve_base_url()
    try:
        resp = httpx.get(f"{base_url}/api/version", timeout=READY_CHECK_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return {"status": "ok", "detail": base_url}
    except httpx.HTTPError as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e} — 규칙 기반(v1)으로 자동 폴백 중"}


def _check_database_ready() -> dict:
    """N-01 감사증적(report_records)은 F-07(/api/v1/reports)에서만 쓰인다 — F-01/F-02의
    핵심 경로인 /api/v1/analyze는 postgres 없이도 동작하므로, stt_worker를 다루는
    apps/api의 /ready와 동일하게 degraded로만 표시하고 503으로 막지 않는다.
    """
    try:
        _report_repository.ping()
        return {"status": "ok", "detail": "postgres"}
    except psycopg.Error as e:
        return {"status": "error", "detail": f"{type(e).__name__}: {e} — 신고 접수 경로만 영향받음"}


@app.get("/ready")
def ready() -> JSONResponse:
    """Ollama가 죽어있어도 이 서비스는 규칙 기반(v1)으로 자동 폴백해 계속 판정을
    내릴 수 있다(ollama_call_analysis_adapter.py 참고) — 그래서 Ollama 다운은
    503(error)이 아니라 status="degraded"와 함께 200을 반환한다: "여전히 요청을
    처리할 수 있지만 판정 품질이 v1 수준으로 낮아졌다"는 뜻. postgres 다운도 같은
    이유로 degraded다 — F-07(신고 접수)만 영향받고 핵심 경로(F-01/F-02)는 항상 동작한다.
    이 서비스가 진짜로 503을 반환해야 할 상황은 현재 구조상 없다.
    """
    ollama_check = _check_ollama_ready()
    db_check = _check_database_ready()
    overall = "ok" if ollama_check["status"] in ("ok", "not_applicable") and db_check["status"] == "ok" else "degraded"
    return JSONResponse(
        content={"status": overall, "checks": {"ollama": ollama_check, "database": db_check}},
        status_code=200,
    )


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest, _role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-01/F-02/F-05: analyze_call_pattern MCP 툴과 동일한 판정 결과를 REST로 제공한다.
    F-04: 위험 정황이 감지되면 rag-worker 유사 사례도 함께 검색해 근거에 결합한다
    (CallAnalysisService 참고). rag-worker가 꺼져 있어도 이 엔드포인트는 정상 동작한다.
    N-02: apps/api와 동일하게 "처리" 행위라 HANDLER 이상 권한이 필요하다.
    N-05: 동시성 제한/스레드풀 위임 이유는 위 _llm_semaphore 선언부 주석 참고.
    """
    async with _llm_semaphore:
        result = await run_in_threadpool(call_analysis_service.execute, req.transcript)
    return serialize_analysis(result.detection, result.risk, result.explanation, result.similar_cases)


class ReportRequest(BaseModel):
    case_summary: str
    risk_level: RiskLevel


@app.post("/api/v1/reports")
async def submit_report(req: ReportRequest, _role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """F-07: submit_report MCP 툴과 동일한 신고 접수(mock) 결과를 REST로 제공한다.
    risk_level이 low/medium/high가 아니면 pydantic이 자동으로 422를 반환한다 (MCP
    툴 쪽의 수동 RiskLevel(risk_level) 검증과 달리, REST는 pydantic 검증으로 충분).
    N-02: analyze와 동일하게 HANDLER 이상 권한이 필요하다.
    """
    record = report_submission_service.submit(req.case_summary, req.risk_level)
    return serialize_report(record)


class EntityInput(BaseModel):
    entity_type: str
    value: str


class CorrelateRequest(BaseModel):
    channel: str
    # text 또는 entities 중 하나는 반드시 있어야 한다(아래 검증 참고). apps/api는 N-03
    # 마스킹 "전" 원문에서 자기가 직접 추출한 entities만 보낸다(원문 자체를 이 서비스로
    # 보내지 않기 위함 — docs/design.md 7장 "N-03과의 상호작용" 참고). text는 Claude
    # Code/합성 문자·이메일 주입 등 원문을 그대로 넣어도 되는 경로용이다.
    text: str | None = None
    entities: list[EntityInput] | None = None
    occurred_at: datetime | None = None
    # 주어지지 않으면 text[:200](text가 있을 때) 또는 빈 문자열을 쓴다. apps/api는
    # 마스킹된 텍스트의 발췌를 명시적으로 넘긴다 — entities만 보내고 원문은 안 보내므로.
    context_excerpt: str | None = None
    # 주어지면 매치된 만큼 가산점을 더한 updated_risk_score/updated_risk_level을 함께
    # 돌려준다(CallAnalysisService.execute()의 call 채널 자동 결합과 동일한 계산).
    current_risk_score: int | None = None


@app.post("/api/v1/correlate")
async def correlate(req: CorrelateRequest, _role: Role = Depends(require_role(Role.HANDLER))) -> dict:
    """우선순위 2: correlate_multichannel_signals MCP 툴과 동일한 크로스채널 상관관계
    결과를 REST로 제공한다 — server.py의 동명 툴 상단 주석 참고(범위/N-03 상호작용 포함).
    """
    try:
        channel = Channel(req.channel)
    except ValueError:
        return JSONResponse(
            status_code=422, content={"error": f"알 수 없는 channel '{req.channel}' — call/sms/email 중 하나여야 합니다."}
        )

    if req.entities is not None:
        try:
            entities = [ExtractedEntity(EntityType(e.entity_type), e.value) for e in req.entities]
        except ValueError as e:
            return JSONResponse(
                status_code=422,
                content={"error": f"알 수 없는 entity_type — phone/account/url 중 하나여야 합니다: {e}"},
            )
    elif req.text is not None:
        entities = extract_entities(req.text)
    else:
        return JSONResponse(status_code=422, content={"error": "text 또는 entities 중 하나는 반드시 있어야 합니다."})

    occurred_at = req.occurred_at or datetime.now(timezone.utc)
    context_excerpt = req.context_excerpt if req.context_excerpt is not None else (req.text[:200] if req.text else "")
    correlation = await run_in_threadpool(
        correlation_service.correlate, channel, entities, occurred_at, context_excerpt, req.current_risk_score
    )
    return serialize_correlation(correlation)
