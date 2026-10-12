# domain 계층: 역방향 신원확인 POC(apps/verify-worker)와의 연결부 모델.
#
# 역할 분담: "AI가 의심하고, 신분증이 확정한다." F-01/F-02 판정이 기관사칭을 의심하면
# 국민에게 "상대 신원을 확인하세요"라고 안내만 하고(decide_verification_prompt), 상대가
# 실제 기관 직원인지는 verify-worker의 서명 검증 결과(CallVerificationRecord)가 확정한다.
# verify-worker는 실제 모바일신분증과 연동하지 않는 모의 시제품이다.

from dataclasses import dataclass
from datetime import datetime

from .entities import CallAnalysisResult, RiskLevel

# mcp-server domain/entities.py PatternCategory.AUTHORITY_IMPERSONATION과 같은 값
# (Role/ExtractedEntity와 같은 이유로 import하지 않고 값만 맞춘다 — 앱 간 직접 의존 금지).
AUTHORITY_IMPERSONATION_CATEGORY = "authority_impersonation"


@dataclass(frozen=True)
class VerificationPrompt:
    """N-04: required=True면 message에 "왜 신원확인을 권하는지"(기관사칭 패턴/고위험)를
    함께 담는다."""

    required: bool
    message: str | None = None


def decide_verification_prompt(result: CallAnalysisResult) -> VerificationPrompt:
    """기관사칭 패턴이 탐지됐거나 고위험이면 상대 신원확인을 안내한다.

    risk_level은 크로스채널 상관관계 가산 "후" 최종 등급을 본다 — 국민에게 보여주는
    위험도 배지와 같은 기준이어야 안내 여부가 화면과 어긋나지 않는다.
    """
    impersonation = next(
        (p for p in result.detected_patterns if p.category == AUTHORITY_IMPERSONATION_CATEGORY), None
    )
    if impersonation is not None:
        keywords = ", ".join(impersonation.matched_keywords[:3])
        evidence = f"기관사칭 의심 표현({keywords})이 탐지되었습니다." if keywords else "기관사칭 의심 패턴이 탐지되었습니다."
    elif result.risk_level == RiskLevel.HIGH:
        evidence = f"고위험({result.risk_score}점)으로 판정되었습니다."
    else:
        return VerificationPrompt(required=False)

    return VerificationPrompt(
        required=True,
        message=(
            f"{evidence} 상대방에게 '확인 코드'를 불러 달라고 해서 실제 기관 직원인지 확인하세요. "
            "확인되기 전에는 송금, 앱 설치, 개인정보 제공을 하지 마세요."
        ),
    )


# 입력 실수 재시도: "없는 코드"는 사칭범일 수도 있지만 어르신이 숫자 하나를 잘못 누른 것일
# 수도 있다. 한 번 틀렸다고 바로 "전화를 끊으세요" + 보호자 알림을 내면 진짜 직원과의 통화를
# 끊게 만들고 보호자도 놀라게 한다 — 그래서 같은 통화에서 연속 첫 번째 code_not_found만 재입력을
# 허용한다. 폐기/만료/재사용/서명 불일치는 입력 실수로 생길 수 없는 결과라 재시도 대상이 아니다.
# 6자리(10^6) 코드를 두 번 안에 맞힐 확률은 2/10^6이라, 한 번 더 기회를 줘도 사칭범에게
# 실질적인 이득은 없다.
RETRYABLE_REASON = "code_not_found"
MAX_CODE_ENTRY_ATTEMPTS = 2


def allows_code_retry(reason: str, previous_records: list["CallVerificationRecord"]) -> bool:
    """이번 결과(reason)를 재입력 안내로 처리할지. previous_records는 같은 통화의 이전 검증
    기록(오래된 것부터). 연속 횟수는 맨 뒤에서부터 code_not_found가 이어진 만큼만 센다 —
    중간에 확인됨 등 다른 결과가 있었으면 거기서 다시 0부터 센다."""
    if reason != RETRYABLE_REASON:
        return False
    consecutive_failures = 0
    for record in reversed(previous_records):
        if record.reason != RETRYABLE_REASON:
            break
        consecutive_failures += 1
    return consecutive_failures + 1 < MAX_CODE_ENTRY_ATTEMPTS


@dataclass(frozen=True)
class GuardianNotification:
    """확인 불가 시 보호자 알림(mock). 실제 문자/푸시 발송은 하지 않고, 알림을 "보냈어야
    하는" 사실만 기록한다 — mcp-server F-07 submit_report mock과 같은 방식."""

    notification_id: str
    call_id: str
    status: str
    created_at: datetime
    note: str


@dataclass(frozen=True)
class CallVerificationRecord:
    """통화 1건에 붙는 신원확인 결과 1건. verify-worker 응답을 그대로 옮기되(N-04: reason/
    message 보존), 표시용 필드는 verified=True일 때만 채워진다."""

    call_id: str
    verified: bool
    reason: str
    message: str
    verified_at: datetime
    institution_name: str | None = None
    staff_display_name: str | None = None
    purpose: str | None = None
    expires_at: str | None = None
    guardian_notification: GuardianNotification | None = None
    # True면 "확인 불가"로 확정하지 않고 재입력을 안내한다(allows_code_retry 참고) — 이때는
    # 보호자 알림도 남기지 않는다.
    retry_allowed: bool = False
