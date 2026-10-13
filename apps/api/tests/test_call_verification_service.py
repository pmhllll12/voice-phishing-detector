# 역방향 신원확인 POC: CallVerificationService 검증. verify-worker HTTP 호출 없이
# IdentityVerificationPort를 페이크로 대체한다 — 서명/폐기/만료 검증 자체는
# apps/verify-worker/tests/test_scenarios.py에서 이미 검증된다. 여기서는 (1) 결과가 통화에
# 붙는지, (2) 확인 불가일 때만 보호자 알림(mock)이 남는지만 본다.

from src.application.services import CallVerificationService
from src.infrastructure.adapters.in_memory_call_verification_log import InMemoryCallVerificationLog
from src.infrastructure.adapters.mock_guardian_notifier import MockGuardianNotifier


class _FakeVerificationPort:
    def __init__(self, response: dict):
        self._response = response
        self.received_code: str | None = None

    def verify(self, code: str, client_key: str | None = None) -> dict:
        self.received_code = code
        self.received_client_key = client_key
        self.calls = getattr(self, "calls", 0) + 1
        return self._response


def _service(response: dict):
    notifier = MockGuardianNotifier()
    log = InMemoryCallVerificationLog()
    port = _FakeVerificationPort(response)
    return CallVerificationService(port, notifier, log), port, notifier, log


def test_verified_result_is_attached_to_call_without_guardian_notification():
    service, port, notifier, log = _service(
        {
            "verified": True,
            "reason": "verified",
            "message": "유효",
            "institution_name": "○○은행(모의)",
            "staff_display_name": "김○○",
            "purpose": "대출 상담 전화",
            "expires_at": "2026-10-12T09:03:00+00:00",
        }
    )

    record = service.execute("call-1", "123456")

    assert port.received_code == "123456"
    assert record.verified is True and record.institution_name == "○○은행(모의)"
    assert record.guardian_notification is None
    assert notifier.sent == []
    assert log.list_for_call("call-1") == [record]


_NOT_FOUND = {"verified": False, "reason": "code_not_found", "message": "발급된 증명이 없습니다."}
_REVOKED = {"verified": False, "reason": "credential_revoked", "message": "자격증명이 폐기되었습니다."}
_VERIFIED = {
    "verified": True,
    "reason": "verified",
    "message": "유효",
    "institution_name": "○○은행(모의)",
    "staff_display_name": "김○○",
    "purpose": "대출 상담 전화",
    "expires_at": "2026-10-12T09:03:00+00:00",
}


def test_first_unknown_code_allows_retry_without_guardian_notification():
    """입력 실수 재시도: 같은 통화의 연속 첫 번째 "없는 코드"는 확인 불가로 확정하지 않는다."""
    service, _port, notifier, log = _service(_NOT_FOUND)

    record = service.execute("call-2", "000000")

    assert record.verified is False and record.reason == "code_not_found"
    assert record.retry_allowed is True
    assert record.guardian_notification is None
    assert notifier.sent == []
    assert log.list_for_call("call-2") == [record]  # 재입력 안내도 기록은 남는다


def test_second_consecutive_unknown_code_logs_mock_guardian_notification():
    service, _port, notifier, log = _service(_NOT_FOUND)

    service.execute("call-2", "000000")
    record = service.execute("call-2", "000001")

    assert record.verified is False and record.retry_allowed is False
    assert record.institution_name is None
    assert record.guardian_notification is not None
    assert record.guardian_notification.call_id == "call-2"
    assert "MOCK" in record.guardian_notification.note
    assert len(notifier.sent) == 1
    assert len(log.list_for_call("call-2")) == 2


def test_revoked_credential_is_unverified_immediately_without_retry():
    """폐기/만료/재사용/위변조는 입력 실수로 생길 수 없어 첫 시도에도 바로 확인 불가."""
    service, _port, notifier, _log = _service(_REVOKED)

    record = service.execute("call-3", "123456")

    assert record.retry_allowed is False
    assert record.guardian_notification is not None
    assert len(notifier.sent) == 1


def test_retry_count_is_per_call():
    service, _port, notifier, _log = _service(_NOT_FOUND)

    first_call = service.execute("call-a", "000000")
    other_call = service.execute("call-b", "000000")

    assert first_call.retry_allowed is True and other_call.retry_allowed is True
    assert notifier.sent == []


def test_retry_count_resets_after_a_different_result():
    service, port, notifier, _log = _service(_NOT_FOUND)

    service.execute("call-4", "000000")  # 재입력 안내
    port._response = _VERIFIED
    service.execute("call-4", "123456")  # 확인됨 → 연속 횟수 초기화
    port._response = _NOT_FOUND
    record = service.execute("call-4", "000000")

    assert record.retry_allowed is True
    assert notifier.sent == []
