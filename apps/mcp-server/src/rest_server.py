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

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from application.dto import serialize_analysis
from application.services import CallAnalysisService
from infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from infrastructure.adapters.ollama_call_analysis_adapter import OllamaCallAnalysisAdapter
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

call_analysis_service = CallAnalysisService(_call_analysis_adapter)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    """F-01/F-02/F-05: analyze_call_pattern MCP 툴과 동일한 판정 결과를 REST로 제공한다."""
    result = call_analysis_service.execute(req.transcript)
    return serialize_analysis(result.detection, result.risk, result.explanation)
