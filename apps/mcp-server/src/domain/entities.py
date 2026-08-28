# domain 계층: 외부 의존성 없는 순수 모델. mcp 패키지도 import하지 않는다.

from dataclasses import dataclass, field
from datetime import datetime
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


@dataclass
class SimilarCase:
    """F-04: rag-worker가 검색한 유사 사기 사례 1건. rag-worker의 /api/v1/similar-cases
    응답을 그대로 옮겨 담는다 (필드명도 동일하게 맞춤)."""

    case_id: str
    title: str
    category: str
    summary: str
    source_note: str
    similarity: float


@dataclass
class CallAnalysisResult:
    """F-01/F-02/F-05 결과를 하나로 묶은 것. CallAnalysisPort.analyze()의 반환 타입.

    detection/risk/explanation을 따로따로 넘기지 않고 묶어두면, 나중에 CallAnalysisPort
    구현체가 하나 더 늘어나도(예: 다른 LLM 제공자) application/infrastructure 양쪽에서
    이 타입 하나만 주고받으면 된다. serialize_analysis()는 이 세 필드를 그대로
    풀어서 기존 API 응답 형식(JSON 키)에 맞춰 직렬화한다 — 즉 어댑터가 바뀌어도
    바깥으로 나가는 JSON 모양은 그대로다.

    similar_cases는 CallAnalysisPort 구현체가 채우지 않는다(F-04는 F-01/F-02와 독립적으로
    동작해야 하므로) — CallAnalysisService.execute()가 판정 이후에 별도로 채워 넣는다
    (application/services.py 참고).
    """

    detection: PatternDetectionResult
    risk: RiskAssessment
    explanation: RiskExplanation
    similar_cases: list[SimilarCase] = field(default_factory=list)


@dataclass
class ReportRecord:
    """F-07: 신고 접수 기록 (mock).

    RFP 데이터 제약상 실제 112/경찰청 신고 API는 호출하지 않는다 — 이 레코드는
    "신고 접수 프로세스가 개시됐다"는 사실 자체를 감사증적으로 남기는 데 목적이 있다.
    """

    report_id: str
    case_summary: str
    risk_level: RiskLevel
    channel: str  # "auto" | "manual" — TODO: 채널이 늘어나면 Enum으로 승격 검토
    status: str  # 지금은 항상 "submitted" (mock이라 상태 전이가 없음)
    submitted_at: datetime
