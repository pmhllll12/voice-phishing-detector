# F-04를 F-05 판정 근거에 결합할 때 쓰는 검색 어댑터. domain/ports.py의
# FraudCaseSearchPort를 구현한다. lookup_fraud_pattern_db MCP 툴(server.py)이 같은
# rag-worker 엔드포인트를 호출하는 것과 별개 경로다 — 그쪽은 Claude Code가 직접 부르는
# 조회용 툴이고, 이 어댑터는 CallAnalysisService가 판정 파이프라인 안에서 자동으로 쓴다.
#
# rag-worker가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/rag-worker && source .venv/bin/activate && uvicorn src.main:app --port 8200

import logging

import httpx

from domain.entities import SimilarCase

logger = logging.getLogger(__name__)


class RagWorkerSearchAdapter:
    # analyze_call_pattern은 rag-worker 없이도 독립적으로 동작해야 한다는 기존 설계
    # 원칙(application/services.py의 ExplanationService 상단 주석 참고) 때문에, 검색
    # 실패는 예외로 올리지 않고 빈 리스트로 조용히 폴백한다. rag-worker 자체가
    # 죽었는지는 그쪽 /ready에서 별도로 관측 가능하므로, 여기서는 "판정 근거에
    # 유사 사례를 못 붙였다"는 사실만 로그로 남긴다.
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._base_url = base_url
        self._timeout = timeout

    def search(self, transcript: str, top_k: int = 2) -> list[SimilarCase]:
        try:
            response = httpx.post(
                f"{self._base_url}/api/v1/similar-cases",
                json={"transcript": transcript, "top_k": top_k},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(
                "rag-worker(%s) 유사사례 검색 실패 — 판정 근거에 유사 사례 결합 없이 진행: %s",
                self._base_url,
                e,
            )
            return []

        return [
            SimilarCase(
                case_id=m["case_id"],
                title=m["title"],
                category=m["category"],
                summary=m["summary"],
                source_note=m["source_note"],
                similarity=m["similarity"],
            )
            for m in response.json()["matches"]
        ]
