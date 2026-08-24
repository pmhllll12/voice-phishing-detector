# apps/mcp-server 진입점 — Claude Code(.mcp.json)가 stdio로 붙는 MCP 툴 서버.
#
# 도구 분리(원문 4번): 통화분석(analyze_call_pattern) / 사기패턴DB조회(lookup_fraud_pattern_db)
# / 신고연동(submit_report, 아직 stub) 3개 MCP 툴을 노출한다.
#
# 여기는 헥사고날 구조의 "infrastructure(MCP 어댑터)" 계층이다. 실제 판정 로직은
# application/services.py에 있고, 이 파일은 그 로직을 MCP 툴 형태로 감싸기만 한다.
# 같은 application 로직을 rest_server.py가 일반 HTTP REST로도 감싸고 있다 (apps/api가
# docker-compose 네트워크에서 이쪽을 호출한다 — MCP 프로토콜 클라이언트를 별도로 구현할
# 필요 없이, 두 어댑터가 같은 서비스를 재사용).
#
# MCPServer는 MCP 공식 Python SDK의 고수준 API로, 함수에 @mcp.tool()만 붙이면
# 자동으로 MCP 툴로 노출해준다 (Claude Code가 .mcp.json을 통해 바로 사용 가능).
# (참고: SDK 구버전에서는 이 클래스명이 FastMCP였음 — mcp 2.0.0부터 MCPServer로 개명)
#
# import 방식 주의: 이 파일은 Claude Code(.mcp.json)에서 `-m` 없이 절대경로
# 스크립트로 직접 실행된다 (cwd 옵션이 기대대로 적용되지 않는 이슈가 있었음).
# 그 결과 sys.path[0]이 이 파일이 있는 src/ 폴더 자체가 되므로, 아래에서
# "src.domain..." 이 아니라 "domain...", "application..." 처럼 src/ 를 루트로
# 보고 import한다 (apps/api, apps/rag-worker는 uvicorn으로 실행되어 cwd가
# apps/xxx 이므로 "src.xxx" 방식을 그대로 쓸 수 있어 서로 다르다).

import os

import httpx
from mcp.server import MCPServer

from application.dto import serialize_analysis
from application.services import ExplanationService, PatternDetectionService, RiskScoringService

mcp = MCPServer("voice-phishing-tools")

pattern_detection_service = PatternDetectionService()
risk_scoring_service = RiskScoringService()
explanation_service = ExplanationService()

# F-04: rag-worker HTTP 서비스 주소. docker-compose로 묶이면 컨테이너 네트워크 주소
# (예: http://rag-worker:8200)로 오버라이드하면 되도록 환경변수로 뺐다.
RAG_WORKER_URL = os.environ.get("RAG_WORKER_URL", "http://localhost:8200")


@mcp.tool()
def analyze_call_pattern(transcript: str) -> dict:
    """F-01/F-02/F-05: 통화/문자 텍스트에서 보이스피싱 패턴(공포조성/기관사칭/긴급송금유도 등)을
    탐지하고, 탐지된 패턴을 근거로 0~100점 위험도 점수와 저/중/고 등급을 산출한 뒤,
    "왜 이렇게 판단했는지"를 근거(매칭 키워드 + 가중치)를 인용한 자연어 설명으로 제공한다
    (N-04 설명가능성: 블랙박스 판정 금지).

    현재는 키워드 기반 규칙 탐지 + 카테고리별 고정 가중치 합산 + 템플릿 기반 문장 생성으로
    구현되어 있다 (domain/pattern_rules.py, application/services.py의 ExplanationService 참고).
    """
    detection = pattern_detection_service.detect(transcript)
    risk = risk_scoring_service.score(detection)
    explanation = explanation_service.generate(detection, risk)
    return serialize_analysis(detection, risk, explanation)


@mcp.tool()
def lookup_fraud_pattern_db(transcript: str, top_k: int = 3) -> dict:
    """F-04: 통화/문자 텍스트와 유사한 기존 사기사례를 rag-worker에서 검색한다.

    rag-worker(v1: 문자 bigram TF-IDF 검색, apps/rag-worker 참고)가 로컬에서 미리
    실행 중이어야 한다:
        cd apps/rag-worker && source .venv/bin/activate && uvicorn src.main:app --port 8200

    TODO: analyze_call_pattern의 F-05 설명(현재는 F-01/F-02만 근거로 사용)에
          이 결과(사례 요약 + 유사도)도 함께 인용하도록 결합하는 것을 검토
    """
    try:
        response = httpx.post(
            f"{RAG_WORKER_URL}/api/v1/similar-cases",
            json={"transcript": transcript, "top_k": top_k},
            timeout=5.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as e:
        return {
            "matches": [],
            "error": (
                f"rag-worker({RAG_WORKER_URL}) 연결 실패: {e}. 먼저 rag-worker를 "
                "실행하세요 (cd apps/rag-worker && source .venv/bin/activate && "
                "uvicorn src.main:app --port 8200)."
            ),
        }


@mcp.tool()
def submit_report(case_summary: str, risk_level: str) -> dict:
    """F-07: 고위험 판정 시 신고 접수 프로세스를 개시한다.

    TODO: 실제 신고 접수 채널 연동은 시뮬레이션 범위 정의 필요
          (가상 프로젝트이므로 실제 112/경찰청 신고 API 호출은 하지 않음 — mock 처리)
    """
    return {
        "report_id": None,
        "status": "not_implemented",
        "note": "TODO: 신고 접수 mock 프로세스 구현 필요",
    }


if __name__ == "__main__":
    # 기본 transport는 stdio — Claude Code(.mcp.json)에서 로컬 프로세스로 바로 테스트 가능.
    # TODO: docker-compose 서비스 간 통신용으로는 transport="streamable-http" 필요
    mcp.run()
