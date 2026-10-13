# 국민용 검증 응답이 허용된 필드만 내보내는지 고정한다. main.py는 import해도 GPU/외부
# 서비스 의존이 없어서(인메모리 + 시드 3건) stt-worker와 달리 직접 import해도 가볍다.

from datetime import datetime, timezone

from src.domain.entities import REASON_MESSAGES, VerificationReason, VerificationResult
from src.main import _serialize_verification


def test_verified_response_exposes_only_display_fields():
    result = VerificationResult(
        verified=True,
        reason=VerificationReason.VERIFIED,
        message=REASON_MESSAGES[VerificationReason.VERIFIED],
        institution_name="○○은행(모의)",
        staff_display_name_masked="김○○",
        purpose="대출 상담 전화",
        expires_at=datetime(2026, 10, 12, 9, 3, tzinfo=timezone.utc),
    )

    payload = _serialize_verification(result)

    assert set(payload) == {
        "verified", "reason", "message", "institution_name", "staff_display_name", "purpose", "expires_at",
    }
    assert payload["staff_display_name"] == "김○○"


def test_unverified_response_has_reason_and_message_only():
    payload = _serialize_verification(VerificationResult.unverified(VerificationReason.CREDENTIAL_REVOKED))

    assert payload == {
        "verified": False,
        "reason": "credential_revoked",
        "message": REASON_MESSAGES[VerificationReason.CREDENTIAL_REVOKED],
    }
