# apps/mcp-server REST 어댑터 — docker-compose 네트워크에서 apps/api가 호출하는 일반
# HTTP 엔드포인트. server.py(MCP stdio, Claude Code 전용)와 완전히 같은 application
# 서비스를 재사용한다 — 판정 로직은 application/services.py 한 곳에만 있고, 두 어댑터는
# 그걸 감싸는 방식만 다르다.
#
# 실행: uvicorn rest_server:app --app-dir src --port 8100 (apps/mcp-server에서 실행)
# --app-dir src 덕분에 sys.path 루트가 apps/mcp-server/src가 되어, server.py와 동일하게
# "domain.xxx"/"application.xxx" 방식의 import가 그대로 통한다 (apps/api·apps/rag-worker의
# "src.xxx" 방식과는 다름 — 이유는 server.py 상단 주석 참고).

import logging
import os

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from application.dto import serialize_analysis, serialize_report
from application.services import CallAnalysisService, ReportSubmissionService
from domain.entities import RiskLevel
from infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from infrastructure.adapters.in_memory_report_repository import InMemoryReportRepository
from infrastructure.adapters.ollama_call_analysis_adapter import (
    OllamaCallAnalysisAdapter,
    _resolve_base_url,
)
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

call_analysis_service = CallAnalysisService(_call_analysis_adapter, RagWorkerSearchAdapter(RAG_WORKER_URL))
report_submission_service = ReportSubmissionService(InMemoryReportRepository())


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


@app.get("/ready")
def ready() -> JSONResponse:
    """Ollama가 죽어있어도 이 서비스는 규칙 기반(v1)으로 자동 폴백해 계속 판정을
    내릴 수 있다(ollama_call_analysis_adapter.py 참고) — 그래서 Ollama 다운은
    503(error)이 아니라 status="degraded"와 함께 200을 반환한다: "여전히 요청을
    처리할 수 있지만 판정 품질이 v1 수준으로 낮아졌다"는 뜻. 이 서비스가 진짜로
    503을 반환해야 할 상황(둘 다 실패)은 현재 구조상 없다 — 규칙 기반은 외부
    의존이 없어 항상 동작한다.
    """
    ollama_check = _check_ollama_ready()
    overall = "ok" if ollama_check["status"] in ("ok", "not_applicable") else "degraded"
    return JSONResponse(content={"status": overall, "checks": {"ollama": ollama_check}}, status_code=200)


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    """F-01/F-02/F-05: analyze_call_pattern MCP 툴과 동일한 판정 결과를 REST로 제공한다.
    F-04: 위험 정황이 감지되면 rag-worker 유사 사례도 함께 검색해 근거에 결합한다
    (CallAnalysisService 참고). rag-worker가 꺼져 있어도 이 엔드포인트는 정상 동작한다.
    """
    result = call_analysis_service.execute(req.transcript)
    return serialize_analysis(result.detection, result.risk, result.explanation, result.similar_cases)


class ReportRequest(BaseModel):
    case_summary: str
    risk_level: RiskLevel


@app.post("/api/v1/reports")
async def submit_report(req: ReportRequest) -> dict:
    """F-07: submit_report MCP 툴과 동일한 신고 접수(mock) 결과를 REST로 제공한다.
    risk_level이 low/medium/high가 아니면 pydantic이 자동으로 422를 반환한다 (MCP
    툴 쪽의 수동 RiskLevel(risk_level) 검증과 달리, REST는 pydantic 검증으로 충분).
    """
    record = report_submission_service.submit(req.case_summary, req.risk_level)
    return serialize_report(record)
