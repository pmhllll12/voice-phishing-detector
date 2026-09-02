# domain 계층: 외부 프레임워크(FastAPI, DB 등)에 의존하지 않는 순수 비즈니스 모델.
# 헥사고날 아키텍처에서 가장 안쪽 계층 — 여기는 "무엇을 판단하는가"만 정의하고
# "어떻게 저장/조회하는가"는 모른다.

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    """F-02: 위험도 3단계 등급 (apps/mcp-server와 값 체계를 맞춤: low/medium/high)"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Role(str, Enum):
    """N-02: 조회/처리/관리자 3단계 권한. 서로 배타적인 카테고리가 아니라 계층 구조다 —
    ADMIN은 HANDLER가 할 수 있는 모든 걸 할 수 있고, HANDLER는 VIEWER가 할 수 있는 모든 걸
    할 수 있다. 실제 대소 비교는 _ROLE_RANK/role_satisfies가 담당한다(Enum 멤버 자체는
    문자열 값이라 대소 비교를 지원하지 않음)."""

    VIEWER = "viewer"  # 조회: 통화 목록/통계 등 판정 결과 열람
    HANDLER = "handler"  # 처리: 통화 분석 실행, 신고 접수 등 실제 액션 수행 (VIEWER 권한 포함)
    ADMIN = "admin"  # 관리자: 전체 권한 (HANDLER 권한 포함)


_ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.HANDLER: 1, Role.ADMIN: 2}


def role_satisfies(actual: Role, required: Role) -> bool:
    """actual 권한이 required 이상인지 (계층 구조 기준)."""
    return _ROLE_RANK[actual] >= _ROLE_RANK[required]


@dataclass(frozen=True)
class ExtractedEntity:
    """우선순위 2(크로스채널 상관관계 탐지): domain/entity_extraction.py가 raw_transcript
    에서 뽑아낸 엔티티 1건. entity_type은 "phone"/"account"/"url" 중 하나 — mcp-server의
    EntityType enum과 값 체계가 동일하지만(Role enum과 같은 이유로) 별도 정의다."""

    entity_type: str
    value: str


@dataclass
class DetectedPatternSummary:
    """F-01 탐지 결과 요약. 실제 탐지 로직은 mcp-server(analyze_call_pattern)에 있고,
    api는 그 결과를 그대로 옮겨 담는다."""

    category: str
    category_label: str
    matched_keywords: list[str] = field(default_factory=list)


@dataclass
class SimilarCaseSummary:
    """F-04: mcp-server가 rag-worker에서 검색해 판정 근거에 결합한 유사 사기 사례 1건.
    mcp-server 응답(similar_cases)을 그대로 옮겨 담는다."""

    case_id: str
    title: str
    category: str
    summary: str
    source_note: str
    similarity: float


@dataclass
class CallAnalysisResult:
    """F-01~F-05의 결과를 표현하는 핵심 도메인 모델.

    실제 판정(F-01/F-02/F-05)은 mcp-server가 수행하고, api는 그 결과를 받아
    call_id/analyzed_at을 부여해 감사증적/대시보드용으로 저장·제공하는 오케스트레이터 역할이다.
    similar_cases(F-04)도 mcp-server가 이미 판정 근거에 결합해서 내려주므로 그대로 옮겨 담는다
    (mcp-server CallAnalysisService 참고) — api 쪽에서 rag-worker를 직접 부르지 않는다.

    masked_transcript(N-03): raw_transcript에서 전화번호/계좌번호/주민등록번호/이름을
    제거한 버전(domain/pii_masking.py). mcp-server 판정 자체도 이 마스킹된 텍스트로
    수행한다(AnalyzeCallService 참고) — 실제 PII 값은 판정에 필요 없고, 로컬이라도
    외부 프로세스(Ollama)로 원문이 나가지 않게 하기 위함. raw_transcript는 감사증적
    보존을 위해 여전히 저장하지만, N-02 RBAC과 결합해 ADMIN 권한에서만 노출한다
    (api/main.py _serialize_call_result 참고) — VIEWER/HANDLER는 masked_transcript만 본다.

    channel(SMS/email 실채널 연동, 2026-09-02): "call"/"email"/"sms" — 어느 채널에서
    들어온 텍스트를 판정한 결과인지 구분한다. F-01/F-02/F-05 로직 자체는 채널 무관하게
    동일하다("통화든 문자든 이메일이든 텍스트 판정 로직은 같다"는 설계 전제,
    docs/design.md 7장 참고) — 이 필드는 감사증적/대시보드에서 구분해서 보여주기 위한
    표시용 메타데이터일 뿐이다.

    TODO:
      - is_deepvoice: bool | None — F-03 (지금은 /api/v1/calls/deepvoice-check가 별도 엔드포인트로
        분리되어 있음, 하나의 통화 판정으로 결합할지는 F-06 대시보드 요구사항 보고 결정)
    """

    call_id: str
    raw_transcript: str
    masked_transcript: str
    risk_score: int
    risk_level: RiskLevel
    detected_patterns: list[DetectedPatternSummary]
    explanation_summary: str
    explanation: str
    analyzed_at: datetime
    similar_cases: list[SimilarCaseSummary] = field(default_factory=list)
    channel: str = "call"


@dataclass
class CategoryCount:
    category: str
    category_label: str
    count: int


@dataclass
class StatsSummary:
    """F-06 관제 대시보드용 집계. N-01 감사증적 로그(postgres)에서 계산한다."""

    total_analyzed: int
    risk_level_counts: dict[str, int]
    category_counts: list[CategoryCount] = field(default_factory=list)


def compute_stats_summary(records: list[CallAnalysisResult]) -> StatsSummary:
    """CallLogPort 구현체(InMemoryCallLogRepository/PostgresCallLogRepository)가 공유하는
    순수 집계 로직 — SQL로 집계하지 않고, 조회된 레코드를 파이썬에서 계산한다(지금 규모에서는
    이쪽이 더 단순하고 두 구현체의 결과가 항상 일치함을 보장하기 쉽다)."""
    risk_level_counts = Counter(r.risk_level.value for r in records)

    category_counter: Counter = Counter()
    category_labels: dict[str, str] = {}
    for record in records:
        for pattern in record.detected_patterns:
            category_counter[pattern.category] += 1
            category_labels[pattern.category] = pattern.category_label

    category_counts = [
        CategoryCount(category=category, category_label=category_labels[category], count=count)
        for category, count in category_counter.most_common()
    ]

    return StatsSummary(
        total_analyzed=len(records),
        risk_level_counts={level.value: risk_level_counts.get(level.value, 0) for level in RiskLevel},
        category_counts=category_counts,
    )


# TODO: 감사증적(N-01)을 위한 AuditLogEntry 도메인 모델 정의
#       (append-only 특성을 어떻게 도메인 레벨에서 보장할지 고민 — 지금 CallAnalysisResult를
#        그대로 감사로그로 쓰고 있지만, 원래는 "판정 결과"와 "감사 이벤트"는 분리하는 것이 정석)
