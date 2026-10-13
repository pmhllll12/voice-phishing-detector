# 역방향 신원확인 POC: 확인 코드 무차별 대입 방어(클라이언트 IP별 실패 횟수 제한) 검증.
# verify-worker 호출은 test_call_verification_service.py의 페이크 포트로 대체하고, 시간은
# now 함수를 바꿔 끼워 슬라이딩 윈도우를 재현한다. 엔드포인트(429 본문)는 TestClient로 본다.

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

import src.main as main
from src.application.services import CallVerificationService
from src.domain.identity_verification import RateLimitPolicy
from src.infrastructure.adapters.in_memory_attempt_store import InMemoryFailedAttemptStore
from src.infrastructure.adapters.in_memory_call_verification_log import InMemoryCallVerificationLog
from src.infrastructure.adapters.mock_guardian_notifier import MockGuardianNotifier
from tests.test_call_verification_service import _NOT_FOUND, _VERIFIED, _FakeVerificationPort

POLICY = RateLimitPolicy(max_failures=5, window_seconds=600)


class _Clock:
    def __init__(self):
        self.current = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current


def _service(response: dict, clock: _Clock | None = None):
    port = _FakeVerificationPort(response)
    notifier = MockGuardianNotifier()
    log = InMemoryCallVerificationLog()
    service = CallVerificationService(
        port, notifier, log, attempt_store=InMemoryFailedAttemptStore(), rate_limit=POLICY, now=clock or _Clock()
    )
    return service, port, notifier, log


def test_retry_allowed_attempt_counts_as_failure_and_sixth_attempt_is_rate_limited():
    """재입력 허용 1회도 실패로 센다: 통화 3건에서 각각 1회차(재입력 안내)·2회차를 섞어 5회
    틀리면 6번째는 어느 통화든 verify-worker를 부르지 않고 rate_limited."""
    service, port, notifier, _log = _service(_NOT_FOUND)
    results = [
        service.execute("call-a", "000000", "10.0.0.1"),  # 재입력 안내(실패 1)
        service.execute("call-a", "000001", "10.0.0.1"),  # 확인 불가(실패 2)
        service.execute("call-b", "000002", "10.0.0.1"),  # 재입력 안내(실패 3)
        service.execute("call-b", "000003", "10.0.0.1"),  # 확인 불가(실패 4)
        service.execute("call-c", "000004", "10.0.0.1"),  # 재입력 안내(실패 5)
    ]
    assert [r.retry_allowed for r in results] == [True, False, True, False, True]
    calls_before = port.calls
    port._response = _VERIFIED  # 맞는 코드를 넣어도

    record = service.execute("call-c", "123456", "10.0.0.1")

    assert port.calls == calls_before  # verify-worker를 부르지 않는다
    assert record.verified is False and record.reason == "rate_limited"
    assert record.retry_allowed is False
    assert record.message
    assert record.guardian_notification is not None  # 확인 불가와 같게 보호자 알림(mock)
    assert len(notifier.sent) == 3  # call-a, call-b 2회차 + 이번 rate_limited


def test_limit_is_per_client_and_forwards_client_ip():
    service, port, _notifier, _log = _service(_NOT_FOUND)
    for i in range(5):
        service.execute(f"call-{i}", "000000", "10.0.0.1")
    port._response = _VERIFIED

    record = service.execute("call-x", "123456", "10.0.0.2")

    assert record.verified is True
    assert port.received_client_key == "10.0.0.2"


def test_window_slides():
    clock = _Clock()
    service, port, _notifier, _log = _service(_NOT_FOUND, clock)
    for i in range(5):
        service.execute(f"call-{i}", "000000", "10.0.0.1")
    assert service.execute("call-9", "000000", "10.0.0.1").reason == "rate_limited"

    clock.current += timedelta(seconds=600)
    port._response = _VERIFIED

    assert service.execute("call-9", "123456", "10.0.0.1").verified is True


def test_repeated_rate_limit_on_same_call_notifies_guardian_only_once():
    """제한에 걸린 뒤 같은 통화로 계속 두드려도 보호자 알림(mock)은 첫 제한 때 한 번만 — 기록은
    매번 남는다. 다른 통화의 첫 제한은 그 통화 기준으로 다시 알린다."""
    service, _port, notifier, log = _service(_NOT_FOUND)
    for _ in range(5):
        service.execute("call-1", "000000", "10.0.0.1")
    sent_before = len(notifier.sent)

    first = service.execute("call-1", "000000", "10.0.0.1")
    repeats = [service.execute("call-1", "000000", "10.0.0.1") for _ in range(3)]
    other_call = service.execute("call-2", "000000", "10.0.0.1")

    assert first.reason == "rate_limited" and first.guardian_notification is not None
    assert all(r.reason == "rate_limited" and r.guardian_notification is None for r in repeats)
    assert other_call.reason == "rate_limited" and other_call.guardian_notification is not None
    assert len(notifier.sent) == sent_before + 2
    assert [r.reason for r in log.list_for_call("call-1")].count("rate_limited") == 4


def test_rate_limited_call_gets_no_more_typo_retry():
    """제한에 걸린 기록이 있는 통화는 윈도우가 지나도 "입력 실수 재입력" 허용이 되살아나지 않는다."""
    clock = _Clock()
    service, _port, _notifier, _log = _service(_NOT_FOUND, clock)
    for _ in range(5):
        service.execute("call-1", "000000", "10.0.0.1")
    assert service.execute("call-1", "000000", "10.0.0.1").reason == "rate_limited"

    clock.current += timedelta(seconds=601)
    record = service.execute("call-1", "000000", "10.0.0.1")

    assert record.reason == "code_not_found"
    assert record.retry_allowed is False
    assert record.guardian_notification is not None


def test_verify_worker_rate_limited_response_is_recorded_as_rate_limited():
    """verify-worker가 자기 쪽 한도로 429(reason=rate_limited)를 돌려준 경우 — 어댑터가 본문을
    그대로 넘기면 api도 rate_limited로 기록하고, 이 실패를 api 쪽 횟수에 이중으로 더하지 않는다."""
    service, _port, notifier, _log = _service(
        {"verified": False, "reason": "rate_limited", "message": "제한"}
    )

    record = service.execute("call-1", "000000", "10.0.0.1")

    assert record.reason == "rate_limited" and record.retry_allowed is False
    assert len(notifier.sent) == 1


def test_endpoint_returns_429_with_reason(monkeypatch):
    service, _port, _notifier, _log = _service(_NOT_FOUND)
    monkeypatch.setattr(main, "call_verification_service", service)
    client = TestClient(main.app)
    headers = {"X-API-Key": "dev-handler-key"}
    before = REGISTRY.get_sample_value("vps_verify_rate_limited_total") or 0.0
    for i in range(5):
        assert client.post(f"/api/v1/calls/c{i}/verification", json={"code": "000000"}, headers=headers).status_code == 200

    response = client.post("/api/v1/calls/c9/verification", json={"code": "000000"}, headers=headers)

    assert response.status_code == 429
    body = response.json()
    assert body["verified"] is False and body["reason"] == "rate_limited"
    assert body["retry_allowed"] is False
    assert body["guardian_notification"]["status"] == "logged"
    assert REGISTRY.get_sample_value("vps_verify_rate_limited_total") == before + 1


def test_policy_rejects_nonsense_values():
    with pytest.raises(ValueError):
        RateLimitPolicy(max_failures=5, window_seconds=0)
