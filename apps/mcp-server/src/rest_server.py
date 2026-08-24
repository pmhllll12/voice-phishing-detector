# apps/mcp-server REST 어댑터 — docker-compose 네트워크에서 apps/api가 호출하는 일반
# HTTP 엔드포인트. server.py(MCP stdio, Claude Code 전용)와 완전히 같은 application
# 서비스를 재사용한다 — 판정 로직은 application/services.py 한 곳에만 있고, 두 어댑터는
# 그걸 감싸는 방식만 다르다.
#
# 실행: uvicorn rest_server:app --app-dir src --port 8100 (apps/mcp-server에서 실행)
# --app-dir src 덕분에 sys.path 루트가 apps/mcp-server/src가 되어, server.py와 동일하게
# "domain.xxx"/"application.xxx" 방식의 import가 그대로 통한다 (apps/api·apps/rag-worker의
# "src.xxx" 방식과는 다름 — 이유는 server.py 상단 주석 참고).

from fastapi import FastAPI
from pydantic import BaseModel

from application.dto import serialize_analysis
from application.services import ExplanationService, PatternDetectionService, RiskScoringService

app = FastAPI(title="Voice Phishing MCP Server (REST adapter)")

pattern_detection_service = PatternDetectionService()
risk_scoring_service = RiskScoringService()
explanation_service = ExplanationService()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


class AnalyzeRequest(BaseModel):
    transcript: str


@app.post("/api/v1/analyze")
async def analyze(req: AnalyzeRequest) -> dict:
    """F-01/F-02/F-05: analyze_call_pattern MCP 툴과 동일한 판정 결과를 REST로 제공한다."""
    detection = pattern_detection_service.detect(req.transcript)
    risk = risk_scoring_service.score(detection)
    explanation = explanation_service.generate(detection, risk)
    return serialize_analysis(detection, risk, explanation)
