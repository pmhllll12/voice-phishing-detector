# domain 계층: 외부 의존성 없는 순수 모델. mcp 패키지도 import하지 않는다.

from dataclasses import dataclass, field
from enum import Enum


class PatternCategory(str, Enum):
    """F-01에서 탐지하는 보이스피싱 패턴 카테고리.

    N-06(확장성) 반영: 새 카테고리를 추가할 때는
      1) 여기에 항목 추가
      2) domain/pattern_rules.py의 PATTERN_RULES에 키워드셋 추가
    만 하면 되고, application/services.py의 탐지 로직은 손댈 필요가 없다.
    """

    AUTHORITY_IMPERSONATION = "authority_impersonation"  # 기관사칭
    FEAR_INDUCEMENT = "fear_inducement"  # 공포조성
    URGENT_TRANSFER = "urgent_transfer"  # 긴급송금유도
    PERSONAL_INFO_REQUEST = "personal_info_request"  # 개인정보요구 (확장 예시로 추가)


CATEGORY_LABELS: dict[PatternCategory, str] = {
    PatternCategory.AUTHORITY_IMPERSONATION: "기관사칭",
    PatternCategory.FEAR_INDUCEMENT: "공포조성",
    PatternCategory.URGENT_TRANSFER: "긴급송금유도",
    PatternCategory.PERSONAL_INFO_REQUEST: "개인정보요구",
}


@dataclass
class DetectedPattern:
    category: PatternCategory
    matched_keywords: list[str] = field(default_factory=list)

    @property
    def category_label(self) -> str:
        return CATEGORY_LABELS[self.category]


@dataclass
class PatternDetectionResult:
    transcript: str
    detected_patterns: list[DetectedPattern] = field(default_factory=list)

    @property
    def has_risk_indicators(self) -> bool:
        return len(self.detected_patterns) > 0


class RiskLevel(str, Enum):
    """F-02: 위험도 3단계 등급."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


RISK_LEVEL_LABELS: dict[RiskLevel, str] = {
    RiskLevel.LOW: "저위험",
    RiskLevel.MEDIUM: "중위험",
    RiskLevel.HIGH: "고위험",
}


# 점수 -> 등급 매핑. 내림차순으로 훑으며 처음으로 score >= threshold인 항목을 채택한다.
# TODO: 합성 데이터셋으로 점수 분포를 확인한 뒤 경계값(40/70)을 보정할 것.
RISK_LEVEL_THRESHOLDS: list[tuple[int, RiskLevel]] = [
    (70, RiskLevel.HIGH),
    (40, RiskLevel.MEDIUM),
    (0, RiskLevel.LOW),
]


@dataclass
class RiskScoreBreakdownItem:
    """N-04(설명가능성): 점수에 어떤 카테고리가 몇 점을 기여했는지 추적 가능하게 기록."""

    category: PatternCategory
    weight: int


@dataclass
class RiskAssessment:
    score: int  # 0~100
    level: RiskLevel
    breakdown: list[RiskScoreBreakdownItem] = field(default_factory=list)


@dataclass
class RiskExplanation:
    """F-05/N-04: 판정 근거 자연어 설명.

    summary(한 줄 결론)와 reasons(카테고리별 근거 문장 리스트)를 구조화된 형태로
    각각 노출해서, 나중에 F-06 대시보드에서 요약/상세를 따로 렌더링할 수 있게 했다.
    narrative는 그 둘을 사람이 읽기 좋은 하나의 문단으로 이어붙인 것.
    """

    summary: str
    reasons: list[str] = field(default_factory=list)
    narrative: str = ""
