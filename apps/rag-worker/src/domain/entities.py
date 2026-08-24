# domain 계층: 외부 의존성 없는 순수 모델.

from dataclasses import dataclass


@dataclass(frozen=True)
class FraudCase:
    """F-04에서 검색 대상이 되는 사기사례 레코드 (합성 데이터셋의 한 건)."""

    case_id: str
    title: str
    category: str
    summary: str
    source_note: str


@dataclass
class SimilarCaseMatch:
    """검색 결과 한 건. similarity는 0.0~1.0 (코사인 유사도)."""

    case: FraudCase
    similarity: float
