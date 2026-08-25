# F-04 성능 비교용 디버그 래퍼: TF-IDF(v1)와 임베딩(v2) 두 어댑터를 같은 쿼리로 모두
# 돌려서 결과를 로그로 남긴다. 실제 응답(return값)은 새 임베딩 어댑터 결과를 쓴다 —
# 이 클래스도 FraudCaseSearchPort를 그대로 구현하므로 application/services.py나
# main.py의 나머지 배선은 이 래퍼로 감싸든 안 감싸든 몰라도 된다 (환경변수
# RAG_DEBUG_COMPARE=1일 때만 main.py에서 이 래퍼로 감싼다).
#
# WHY 매 요청마다 두 번 검색하는가: 이건 프로덕션 경로가 아니라 "TF-IDF에서 임베딩으로
# 바꿨을 때 실제로 순위가 어떻게 달라지는가"를 로그로 눈으로 확인하기 위한 임시 비교
# 도구다. 코퍼스가 지금처럼 10건이면 비용이 무시할 만하지만, 코퍼스가 커지면 상시
# 켜두지 말고 필요할 때만 RAG_DEBUG_COMPARE=1로 켤 것.

import logging

from src.domain.entities import SimilarCaseMatch
from src.domain.ports import FraudCaseSearchPort

logger = logging.getLogger(__name__)


class DebugCompareAdapter:
    def __init__(
        self,
        primary: FraudCaseSearchPort,
        comparison: FraudCaseSearchPort,
        comparison_label: str = "tfidf",
    ):
        self._primary = primary
        self._comparison = comparison
        self._comparison_label = comparison_label

    def search(self, query: str, top_k: int) -> list[SimilarCaseMatch]:
        primary_matches = self._primary.search(query, top_k)
        comparison_matches = self._comparison.search(query, top_k)
        self._log_comparison(query, primary_matches, comparison_matches)
        return primary_matches

    def _log_comparison(
        self,
        query: str,
        primary_matches: list[SimilarCaseMatch],
        comparison_matches: list[SimilarCaseMatch],
    ) -> None:
        primary_ranked = ", ".join(
            f"{m.case.case_id}({m.similarity:.3f})" for m in primary_matches
        )
        comparison_ranked = ", ".join(
            f"{m.case.case_id}({m.similarity:.3f})" for m in comparison_matches
        )
        logger.info(
            "[F-04 debug-compare] query=%r\n  embedding : %s\n  %-9s: %s",
            query,
            primary_ranked,
            self._comparison_label,
            comparison_ranked,
        )
