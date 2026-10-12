# 확인 코드 무차별 대입 방어(domain/rate_limit.py, RateLimitedVerifyService) 검증.
# 시간은 test_scenarios.py의 가짜 시계로 돌리고, 엔드포인트(429, IP 판별)는 httpx 의존성을
# 들이지 않으려고 함수를 직접 호출한다.

import asyncio
import json

import pytest
from prometheus_client import REGISTRY
from starlette.requests import Request

from src.application.services import RateLimitedVerifyService
from src.domain.entities import VerificationReason
from src.domain.rate_limit import RateLimitPolicy
from src.infrastructure.adapters.in_memory_attempt_store import InMemoryFailedAttemptStore
from src.main import VerifyRequest, _client_key, verify
from tests.test_scenarios import _issue_bank_staff, _System

POLICY = RateLimitPolicy(max_failures=5, window_seconds=600)


@pytest.fixture
def system() -> _System:
    return _System()


@pytest.fixture
def limited(system):
    return RateLimitedVerifyService(system.verify, InMemoryFailedAttemptStore(), system.clock, POLICY)


def _wrong_code(system) -> str:
    return "000000" if system.proofs.get_by_code("000000") is None else "999999"


def test_sixth_attempt_after_five_failures_is_rate_limited_even_with_correct_code(system, limited):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")
    for _ in range(5):
        assert limited.execute("10.0.0.1", _wrong_code(system)).reason == VerificationReason.CODE_NOT_FOUND

    result = limited.execute("10.0.0.1", proof.code)

    assert result.verified is False
    assert result.reason == VerificationReason.RATE_LIMITED
    assert result.message
    # 제한으로 거절된 시도는 정상 증명을 소모하지 않는다
    assert system.proofs.get_by_code(proof.code).used is False


def test_limit_is_per_client(system, limited):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")
    for _ in range(5):
        limited.execute("10.0.0.1", _wrong_code(system))

    assert limited.execute("10.0.0.2", proof.code).verified is True


def test_successes_are_not_counted(system, limited):
    for _ in range(6):
        credential = _issue_bank_staff(system)
        proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")
        assert limited.execute("10.0.0.1", proof.code).verified is True
    for _ in range(4):
        limited.execute("10.0.0.1", _wrong_code(system))

    assert limited.execute("10.0.0.1", _wrong_code(system)).reason == VerificationReason.CODE_NOT_FOUND


def test_window_slides(system, limited):
    """실패 5회 후 막히지만, 첫 실패가 윈도우(600초) 밖으로 나가면 한 번 더 시도할 수 있다.
    제한으로 거절된 시도는 실패 횟수에 다시 더하지 않는다."""
    limited.execute("10.0.0.1", _wrong_code(system))  # t=0
    system.clock.advance(100)
    for _ in range(4):  # t=100
        limited.execute("10.0.0.1", _wrong_code(system))
    assert limited.execute("10.0.0.1", _wrong_code(system)).reason == VerificationReason.RATE_LIMITED

    system.clock.advance(500)  # t=600: t=0 실패는 윈도우 밖, t=100 실패 4회는 안
    assert limited.execute("10.0.0.1", _wrong_code(system)).reason == VerificationReason.CODE_NOT_FOUND
    assert limited.execute("10.0.0.1", _wrong_code(system)).reason == VerificationReason.RATE_LIMITED

    system.clock.advance(100)  # t=700: 모든 실패가 윈도우 밖
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")
    assert limited.execute("10.0.0.1", proof.code).verified is True


def test_policy_rejects_nonsense_values():
    with pytest.raises(ValueError):
        RateLimitPolicy(max_failures=0, window_seconds=600)


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "POST", "path": "/api/v1/verify", "headers": headers, "client": (peer, 5000)})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.7", None, "203.0.113.7"),
        ("203.0.113.7", "198.51.100.1", "203.0.113.7"),  # 신뢰 프록시가 아니면 헤더 무시
        ("127.0.0.1", "198.51.100.1", "198.51.100.1"),  # api(신뢰 프록시)가 넘긴 클라이언트 IP
        ("127.0.0.1", "1.1.1.1, 198.51.100.1", "198.51.100.1"),  # 왼쪽(클라이언트가 넣은 값)은 안 믿음
        ("127.0.0.1", "not-an-ip", "127.0.0.1"),
        ("127.0.0.1", None, "127.0.0.1"),
    ],
)
def test_client_key(peer, forwarded, expected):
    assert _client_key(_request(peer, forwarded)) == expected


def test_verify_endpoint_returns_429_with_reason_after_limit():
    peer = "203.0.113.99"  # 다른 테스트와 기록이 섞이지 않게 이 테스트 전용 IP
    before = REGISTRY.get_sample_value("vps_verify_rate_limited_total") or 0.0
    for _ in range(5):
        body = asyncio.run(verify(VerifyRequest(code="000000"), _request(peer)))
        assert body["reason"] == "code_not_found"

    response = asyncio.run(verify(VerifyRequest(code="000000"), _request(peer)))

    assert response.status_code == 429
    assert json.loads(response.body) == {
        "verified": False,
        "reason": "rate_limited",
        "message": "짧은 시간에 확인 코드를 너무 여러 번 틀렸습니다(무차별 대입 의심). 검증하지 않고 거절했습니다.",
    }
    assert REGISTRY.get_sample_value("vps_verify_rate_limited_total") == before + 1
