# apps/mcp-server 진입점 — Claude Code(.mcp.json)가 stdio로 붙는 MCP 툴 서버.
#
# 도구 분리(원문 4번): 통화분석(analyze_call_pattern) / 사기패턴DB조회(lookup_fraud_pattern_db)
# / 신고연동(submit_report) 3개 MCP 툴을 노출한다.
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

import logging
import os
from datetime import datetime, timezone

import httpx
from mcp.server import MCPServer

from application.dto import serialize_analysis, serialize_correlation, serialize_report
from application.services import CallAnalysisService, MultichannelCorrelationService, ReportSubmissionService
from domain.entities import Channel, RiskLevel
from domain.entity_extraction import extract_entities
from infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from infrastructure.adapters.ollama_call_analysis_adapter import OllamaCallAnalysisAdapter
from infrastructure.adapters.postgres_channel_signal_repository import PostgresChannelSignalRepository
from infrastructure.adapters.postgres_report_repository import PostgresReportRepository
from infrastructure.adapters.rag_worker_search_adapter import RagWorkerSearchAdapter
from infrastructure.adapters.rule_based_call_analysis_adapter import RuleBasedCallAnalysisAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

mcp = MCPServer("voice-phishing-tools")

# F-01/F-02 v2: 기본은 Ollama(로컬 LLM), 실패 시 규칙 기반(v1)으로 자동 폴백.
# CALL_ANALYSIS_BACKEND=rule로 강제로 v1만 쓸 수 있고(Ollama가 아예 없는 환경 등),
# LLM_DEBUG_COMPARE=1이면 v1/v2를 동시에 돌려서 점수 차이를 로그로 비교한다.
_rule_based_adapter = RuleBasedCallAnalysisAdapter()
_ollama_adapter = OllamaCallAnalysisAdapter(fallback=_rule_based_adapter)

if os.environ.get("CALL_ANALYSIS_BACKEND", "llm").lower() == "rule":
    _call_analysis_adapter = _rule_based_adapter
elif os.environ.get("LLM_DEBUG_COMPARE", "").lower() in ("1", "true", "yes"):
    _call_analysis_adapter = DebugCompareAdapter(_ollama_adapter, _rule_based_adapter)
else:
    _call_analysis_adapter = _ollama_adapter

# F-04: rag-worker HTTP 서비스 주소. docker-compose로 묶이면 컨테이너 네트워크 주소
# (예: http://rag-worker:8200)로 오버라이드하면 되도록 환경변수로 뺐다.
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
report_submission_service = ReportSubmissionService(PostgresReportRepository(DATABASE_URL))


@mcp.tool()
def analyze_call_pattern(transcript: str) -> dict:
    """F-01/F-02/F-05: 통화/문자 텍스트에서 보이스피싱 패턴(공포조성/기관사칭/긴급송금유도 등)을
    탐지하고, 탐지된 패턴을 근거로 0~100점 위험도 점수와 저/중/고 등급을 산출한 뒤,
    "왜 이렇게 판단했는지"를 근거를 인용한 자연어 설명으로 제공한다
    (N-04 설명가능성: 블랙박스 판정 금지).

    기본은 로컬 Ollama LLM(문맥 이해 기반 판단)이고, 호출 실패 시 키워드 규칙 기반(v1)으로
    자동 폴백한다 (infrastructure/adapters/ollama_call_analysis_adapter.py,
    rule_based_call_analysis_adapter.py 참고).

    F-04: 위험 정황이 감지되면 rag-worker에서 유사 사기 사례를 검색해 판정 근거에
    함께 인용한다(응답의 similar_cases, explanation 참고). rag-worker가 꺼져 있어도
    이 툴 자체는 계속 정상 동작한다 — CallAnalysisService 상단 주석 참고.
    """
    result = call_analysis_service.execute(transcript)
    return serialize_analysis(result.detection, result.risk, result.explanation, result.similar_cases)


@mcp.tool()
def lookup_fraud_pattern_db(transcript: str, top_k: int = 3) -> dict:
    """F-04: 통화/문자 텍스트와 유사한 기존 사기사례를 rag-worker에서 검색한다.

    rag-worker(v1: 문자 bigram TF-IDF 검색, apps/rag-worker 참고)가 로컬에서 미리
    실행 중이어야 한다:
        cd apps/rag-worker && source .venv/bin/activate && uvicorn src.main:app --port 8200

    이 툴은 Claude Code가 직접 조회할 때 쓰는 별도 경로다 — analyze_call_pattern은
    이미 자체적으로 rag-worker를 호출해 판정 근거에 유사 사례를 결합한다
    (RagWorkerSearchAdapter, application/services.py의 CallAnalysisService 참고).
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
    """F-07: 고위험 판정 시 신고 접수 프로세스를 개시한다 (mock).

    risk_level은 "low"/"medium"/"high" 중 하나여야 한다 (analyze_call_pattern의
    risk_level 출력과 동일한 값 체계). risk_level이 "high"이면 자동 접수(auto),
    그 외에는 수동 검토(manual) 채널로 분류한다.

    ⚠️ RFP 데이터 제약: 실제 112/경찰청 신고 API는 호출하지 않는다. 이 툴은
    "신고 접수 프로세스가 개시됐다"는 사실을 기록하고 report_id를 발급하는 mock이다.
    """
    try:
        level = RiskLevel(risk_level)
    except ValueError:
        return {
            "report_id": None,
            "status": "rejected",
            "error": f"알 수 없는 risk_level '{risk_level}' — low/medium/high 중 하나여야 합니다.",
        }

    record = report_submission_service.submit(case_summary, level)
    return serialize_report(record)


@mcp.tool()
def correlate_multichannel_signals(
    channel: str, text: str, occurred_at: str | None = None
) -> dict:
    """우선순위 2: 통화/문자/이메일 텍스트에서 전화번호/계좌번호/URL을 추출해 채널 신호로
    기록하고, 다른 채널에 같은 엔티티가 최근(기본 30분) 등장했는지 확인한다.

    시중 보이스피싱 차단 앱은 자기 채널(통화면 통화만) 안에서만 판단하지만, 실제
    공격은 "전화로 신뢰 형성 → 문자로 악성 링크 → 이메일로 위장 공문" 같은 다단계
    공격으로 진화하고 있다 — 이 툴은 그 연계를 잡는다.

    channel은 "call"/"sms"/"email" 중 하나. analyze_call_pattern은 call 채널 신호를
    이미 자동으로 기록/조회하므로(CallAnalysisService 참고), 이 툴은 주로 sms/email
    합성 이벤트를 수동 주입해 상관관계를 검증하는 용도다 — 실제 SMS 수신/이메일 연동
    (Gmail API 등)은 이번 범위 밖이다.

    ⚠️ N-03과의 상호작용: apps/api를 거치는 통화(REST 경로)는 mcp-server에 도달하기
    전에 이미 마스킹되어 있어 전화번호/계좌번호가 "[전화번호]"/"[계좌번호]" 태그로
    치환된 상태다 — 그 경로에서는 URL 상관관계만 자동 작동한다. 이 툴로 원문을 직접
    넣으면(테스트/시연 목적) 정상적으로 전화번호/계좌번호까지 추출된다.
    """
    try:
        channel_enum = Channel(channel)
    except ValueError:
        return {"error": f"알 수 없는 channel '{channel}' — call/sms/email 중 하나여야 합니다."}

    if occurred_at:
        try:
            parsed_occurred_at = datetime.fromisoformat(occurred_at)
        except ValueError:
            return {"error": f"occurred_at은 ISO8601 형식이어야 합니다: '{occurred_at}'"}
    else:
        parsed_occurred_at = datetime.now(timezone.utc)

    entities = extract_entities(text)
    correlation = correlation_service.correlate(
        channel_enum, entities, occurred_at=parsed_occurred_at, context_excerpt=text[:200]
    )
    return serialize_correlation(correlation)


if __name__ == "__main__":
    # 기본 transport는 stdio — Claude Code(.mcp.json)에서 로컬 프로세스로 바로 테스트 가능.
    # TODO: docker-compose 서비스 간 통신용으로는 transport="streamable-http" 필요
    mcp.run()
