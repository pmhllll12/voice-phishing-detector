# application 계층: F-04 유스케이스.
# 실제 검색 알고리즘은 infrastructure의 어댑터가 구현하고, 여기서는
# domain/ports.py의 FraudCaseSearchPort 인터페이스로만 의존한다.

from src.domain.entities import SimilarCaseMatch
from src.domain.ports import FraudCaseSearchPort


class SimilarCaseSearchService:
    """F-04: 통화/문자 텍스트와 유사한 기존 사기사례를 검색한다.

    TODO (고도화 순서 제안):
      1. (완료) 문자 n-gram TF-IDF 기반 유사도 검색으로 1차 구현
         (infrastructure/adapters/tfidf_similarity_adapter.py 참고)
      2. 합성 데이터셋을 확장하고 검색 품질(재현율) 검증
      3. sentence-transformers 등 실제 임베딩 모델 + pgvector로 교체 검토
         (이 서비스와 FraudCaseSearchPort 인터페이스는 그대로 유지)
      4. F-05 판정 근거 문장 생성 시 이 결과(사례 요약 + 유사도)를 근거로 활용
    """

    def __init__(self, search_port: FraudCaseSearchPort):
        self._search_port = search_port

    def execute(self, transcript: str, top_k: int = 3) -> list[SimilarCaseMatch]:
        return self._search_port.search(transcript, top_k)
