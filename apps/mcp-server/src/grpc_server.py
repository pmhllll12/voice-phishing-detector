# apps/mcp-server 세 번째 진입점 — N-06 확장성 검증(2026-09-01)용 gRPC 어댑터.
#
# server.py(MCP stdio)와 rest_server.py(REST) 둘 다 같은 application 서비스
# (CallAnalysisService)를 감싸기만 한다는 게 이 프로젝트의 N-06 핵심 주장인데, 그
# 주장은 "진입점을 2개 만들어봤다"까지만 실측된 상태였다 — "새 진입점 프로토콜을
# 추가하는 것"(예: gRPC) 자체는 검증 안 된 확장 축으로 docs/design.md에 정직하게
# 남아있었다. 이 파일이 그 축을 실제로 검증한다: CallAnalysisService를 그대로
# 재사용하고, application/domain 계층은 1줄도 안 건드렸다(N-06의 다른 3개 축과
# 동일한 "application 계층 diff 0줄" 패턴).
#
# 배선 코드(_rule_based_adapter/_ollama_adapter/call_analysis_service 생성)는
# rest_server.py/server.py와 완전히 동일하게 복붙했다 — 그쪽 상단 주석과 같은 이유로
# (공유 모듈로 뽑을 만큼 커지면 그때 리팩터링).
#
# N-02 접근통제: mcp-server REST 어댑터와 동일한 X-API-Key 저장소(API_KEYS, Role)를
# 재사용해 gRPC metadata("x-api-key")로 인증한다 — FastAPI의 Depends(require_role)는
# 이 프로토콜에서 못 쓰지만, 그 밑에 있는 도메인 모델(Role/role_satisfies)과 API_KEYS
# 저장소는 그대로 재사용된다(_ApiKeyAuthInterceptor 참고) — "접근통제 체계가 세 번째
# 진입점에도 재설계 없이 확장되는가"까지 같이 검증한다.
#
# 실행: python grpc_server.py (apps/mcp-server에서, .venv 활성화 후) — 기본 포트 8101
# (REST 어댑터의 8100과 겹치지 않게). docker-compose에는 아직 등록하지 않았다 —
# 이 파일의 목적은 "새 진입점 프로토콜 추가가 실제로 가능한가"를 증명하는 것이지,
# gRPC를 프로덕션 배포 대상으로 삼는 게 아니다(README "mcp-server gRPC 진입점" 참고).

import logging
import os
from concurrent import futures

import grpc

from application.services import CallAnalysisService
from domain.entities import Role, role_satisfies
from infrastructure.adapters.api_key_role_auth import API_KEYS
from infrastructure.adapters.ollama_call_analysis_adapter import OllamaCallAnalysisAdapter
from infrastructure.adapters.rag_worker_search_adapter import RagWorkerSearchAdapter
from infrastructure.adapters.rule_based_call_analysis_adapter import RuleBasedCallAnalysisAdapter
from infrastructure.grpc_generated import voice_phishing_pb2, voice_phishing_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_rule_based_adapter = RuleBasedCallAnalysisAdapter()
_ollama_adapter = OllamaCallAnalysisAdapter(fallback=_rule_based_adapter)
_call_analysis_adapter = _rule_based_adapter if os.environ.get("CALL_ANALYSIS_BACKEND", "llm").lower() == "rule" else _ollama_adapter

RAG_WORKER_URL = os.environ.get("RAG_WORKER_URL", "http://localhost:8200")

call_analysis_service = CallAnalysisService(_call_analysis_adapter, RagWorkerSearchAdapter(RAG_WORKER_URL))
# submit_report(F-07)는 이 파일에서 아직 gRPC로 노출하지 않는다 — Analyze RPC
# 1개만 검증 범위로 잡았다(위 상단 주석 "이 파일의 목적" 참고). 노출하려면
# ReportSubmissionService를 여기서도 만들고 .proto에 RPC를 추가하면 되는데, 그건
# 이미 검증된 패턴(RPC 1개 추가)의 반복이라 범위에서 뺐다.


def _require_handler_role(context: grpc.ServicerContext) -> None:
    metadata = dict(context.invocation_metadata())
    api_key = metadata.get("x-api-key")
    if api_key is None or api_key not in API_KEYS:
        context.abort(grpc.StatusCode.UNAUTHENTICATED, "유효한 x-api-key metadata가 필요합니다.")
    role = API_KEYS[api_key]
    if not role_satisfies(role, Role.HANDLER):
        context.abort(
            grpc.StatusCode.PERMISSION_DENIED,
            f"이 작업은 {Role.HANDLER.value} 이상 권한이 필요합니다 (현재 키 권한: {role.value}).",
        )


class VoicePhishingAnalysisServicer(voice_phishing_pb2_grpc.VoicePhishingAnalysisServicer):
    def Analyze(self, request, context):
        _require_handler_role(context)

        result = call_analysis_service.execute(request.transcript)
        detection, risk, explanation, similar_cases = (
            result.detection,
            result.risk,
            result.explanation,
            result.similar_cases,
        )

        return voice_phishing_pb2.AnalyzeResponse(
            detected_patterns=[
                voice_phishing_pb2.DetectedPattern(
                    category=p.category.value,
                    category_label=p.category_label,
                    matched_keywords=p.matched_keywords,
                )
                for p in detection.detected_patterns
            ],
            pattern_count=len(detection.detected_patterns),
            has_risk_indicators=detection.has_risk_indicators,
            risk_score=risk.score,
            risk_level=risk.level.value,
            explanation_summary=explanation.summary,
            explanation_reasons=explanation.reasons,
            explanation=explanation.narrative,
            similar_cases=[
                voice_phishing_pb2.SimilarCase(
                    case_id=c.case_id,
                    title=c.title,
                    category=c.category,
                    summary=c.summary,
                    source_note=c.source_note,
                    similarity=c.similarity,
                )
                for c in similar_cases
            ],
        )


def serve(port: int = 8101) -> tuple[grpc.Server, int]:
    """port=0이면 OS가 빈 포트를 골라준다 — 테스트에서 실제 포트 충돌 없이 서버를
    띄우는 용도(test_grpc_server.py 참고)."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    voice_phishing_pb2_grpc.add_VoicePhishingAnalysisServicer_to_server(VoicePhishingAnalysisServicer(), server)
    bound_port = server.add_insecure_port(f"[::]:{port}")
    server.start()
    logger.info("gRPC 서버 시작: [::]:%d", bound_port)
    return server, bound_port


if __name__ == "__main__":
    grpc_server, _ = serve()
    grpc_server.wait_for_termination()
