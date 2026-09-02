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


class Role(str, Enum):
    """N-02: 조회/처리/관리자 3단계 권한. apps/api/src/domain/entities.py의 Role과 값/의미가
    동일하다 — 별도 패키지로 공유하지 않고 복붙한 이유는 rest_server.py 상단 주석과 같다
    ("공유 모듈로 뽑을 만큼 커지면 그때 리팩터링"). ADMIN은 HANDLER가 할 수 있는 모든 걸
    할 수 있고, HANDLER는 VIEWER가 할 수 있는 모든 걸 할 수 있다 — 실제 대소 비교는
    _ROLE_RANK/role_satisfies가 담당한다."""

    VIEWER = "viewer"
    HANDLER = "handler"  # 처리: /api/v1/analyze, /api/v1/reports 호출
    ADMIN = "admin"


_ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.HANDLER: 1, Role.ADMIN: 2}


def role_satisfies(actual: Role, required: Role) -> bool:
    """actual 권한이 required 이상인지 (계층 구조 기준)."""
    return _ROLE_RANK[actual] >= _ROLE_RANK[required]


RISK_LEVEL_LABELS: dict[RiskLevel, str] = {
    RiskLevel.LOW: "저위험",
    RiskLevel.MEDIUM: "중위험",
    RiskLevel.HIGH: "고위험",
}


# 점수 -> 등급 매핑. 내림차순으로 훑으며 처음으로 score >= threshold인 항목을 채택한다.
# 2026-08-28: data/synthetic_call_transcripts.json으로 검증 완료 — 경계값(40/70) 그대로
# 유지 (pattern_rules.py의 CATEGORY_WEIGHTS 상단 주석 참고).
RISK_LEVEL_THRESHOLDS: list[tuple[int, RiskLevel]] = [
    (70, RiskLevel.HIGH),
    (40, RiskLevel.MEDIUM),
    (0, RiskLevel.LOW),
]


def risk_level_for_score(score: int) -> RiskLevel:
    """점수 -> 등급 매핑을 RiskScoringService 밖에서도 재사용할 수 있게 뽑은 free
    function. 크로스채널 상관관계 가산점(우선순위 2) 적용 후 점수가 바뀌었을 때
    등급을 다시 매기는 데 쓴다 — 등급 경계값의 단일 소스는 여전히 RISK_LEVEL_THRESHOLDS
    하나뿐이다(application/services.py의 RiskScoringService._level_for도 이 함수로 위임)."""
    for threshold, level in RISK_LEVEL_THRESHOLDS:
        if score >= threshold:
            return level
    return RiskLevel.LOW


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
    # 우선순위 2(크로스채널 상관관계): score에 이미 반영된 가산점 중 상관관계로 인한
    # 부분만 별도로 추적한다(N-04: breakdown이 F-01 카테고리별 가중치만 다루므로,
    # "왜 이 점수인가"를 완전히 설명하려면 이 필드도 함께 봐야 한다).
    correlation_boost: int = 0


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


class Channel(str, Enum):
    """우선순위 2(크로스채널 상관관계 탐지): 탐지 기록이 발생한 채널.

    F-06까지는 통화(call) 채널만 실제로 데이터가 들어온다 — sms/email은 신규 유입
    경로(실제 SMS 수신, Gmail API 연동 등)가 이번 범위 밖이라, correlate_multichannel_signals
    MCP 툴로 합성 문자/이메일 이벤트를 수동 주입해서 상관관계 로직만 검증한다
    (docs/RFP.md 4장 데이터 제약과 같은 이유 — 실채널 연동은 범위가 크므로 별도 상의).
    """

    CALL = "call"
    SMS = "sms"
    EMAIL = "email"


CHANNEL_LABELS: dict[Channel, str] = {
    Channel.CALL: "통화",
    Channel.SMS: "문자",
    Channel.EMAIL: "이메일",
}


class EntityType(str, Enum):
    """크로스채널 상관관계의 매칭 키가 되는 엔티티 종류. domain/entity_extraction.py가
    텍스트에서 이 타입들을 정규식으로 추출한다."""

    PHONE = "phone"
    ACCOUNT = "account"
    URL = "url"


ENTITY_TYPE_LABELS: dict[EntityType, str] = {
    EntityType.PHONE: "전화번호",
    EntityType.ACCOUNT: "계좌번호",
    EntityType.URL: "URL",
}


@dataclass(frozen=True)
class ExtractedEntity:
    """entity_extraction.py가 텍스트에서 뽑아낸 엔티티 1건. value는 정규화된 원본 값
    (전화번호/계좌번호는 숫자만, URL은 소문자+뒤 구두점 제거) — 채널마다 표기 형식이
    달라도("010-1234-5678" vs "01012345678") 같은 값이면 매칭되도록 하기 위함."""

    entity_type: EntityType
    value: str


@dataclass
class ChannelSignal:
    """한 채널 이벤트(통화 1건/문자 1건/이메일 1건)에서 추출된 엔티티들을 묶은 것.
    ChannelSignalRepositoryPort.record()로 저장되어 이후 다른 채널 이벤트의
    상관관계 조회 대상이 된다."""

    channel: Channel
    entities: list[ExtractedEntity]
    occurred_at: datetime
    context_excerpt: str


@dataclass
class CorrelationMatch:
    """다른 채널에서 발견된 동일 엔티티 1건. entity_value는 항상 마스킹된 표시용 값이다
    (원본 값은 저장소에만 있고 바깥으로 안 나간다 — N-03과 같은 원칙,
    application/services.py의 _mask_for_display 참고)."""

    entity_type: EntityType
    entity_value: str  # 마스킹된 표시값
    matched_channel: Channel
    matched_at: datetime
    context_excerpt: str


@dataclass
class CorrelationResult:
    """MultichannelCorrelationService.correlate()의 결과. current_risk_score가 주어졌을
    때만(즉 CallAnalysisService가 F-02 점수와 함께 호출했을 때만) updated_risk_score/
    updated_risk_level이 채워진다 — 단독으로 correlate_multichannel_signals 툴을
    호출할 때는(예: 합성 문자/이메일 주입) None으로 남는다.

    matches(크로스채널 재등장)와 flagged_urls(Google Safe Browsing 악성 URL 확인)는
    서로 다른 근거라 risk_boost에 둘 다 반영되더라도(N-04) 필드를 분리해 "왜"를
    구분할 수 있게 했다 — threat_intelligence_port가 없으면(선택 의존) 항상 빈 리스트."""

    matches: list[CorrelationMatch] = field(default_factory=list)
    flagged_urls: list[str] = field(default_factory=list)
    risk_boost: int = 0
    reasons: list[str] = field(default_factory=list)
    updated_risk_score: int | None = None
    updated_risk_level: RiskLevel | None = None


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


@dataclass
class EmailMessage:
    """우선순위 2(SMS/email 실채널 연동, 2026-09-02): Gmail 받은편지함에서 읽어온
    메일 1건. EmailSourcePort.fetch_new_emails()의 반환 타입 — Gmail API 응답 형식을
    이 계층까지 그대로 노출하지 않고 여기서 필요한 필드만 뽑아 순수 도메인 모델로
    옮겨 담는다(infrastructure/adapters/gmail_email_source_adapter.py 참고)."""

    message_id: str
    subject: str
    body: str
    received_at: datetime
