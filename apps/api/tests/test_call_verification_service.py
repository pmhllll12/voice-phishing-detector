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

    def verify(self, code: str) -> dict:
        self.received_code = code
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


def test_unverified_result_logs_mock_guardian_notification():
    service, _port, notifier, log = _service(
        {"verified": False, "reason": "code_not_found", "message": "발급된 증명이 없습니다."}
    )

    record = service.execute("call-2", "000000")

    assert record.verified is False and record.reason == "code_not_found"
    assert record.institution_name is None
    assert record.guardian_notification is not None
    assert record.guardian_notification.call_id == "call-2"
    assert "MOCK" in record.guardian_notification.note
    assert len(notifier.sent) == 1
    assert log.list_for_call("call-2") == [record]
