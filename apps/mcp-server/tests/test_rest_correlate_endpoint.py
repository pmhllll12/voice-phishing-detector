# POST /api/v1/correlate 라우팅/인증/직렬화만 확인한다 — 실제 상관관계 매칭 로직은
# test_multichannel_correlation_service.py, postgres 연동은
# test_postgres_channel_signal_repository.py에서 이미 검증한다. test_rest_report_endpoint.py와
# 같은 이유로 postgres 없이 돌 수 있도록 가짜 저장소로 바꿔치기한다.

import pytest
from fastapi.testclient import TestClient

import rest_server
from application.services import MultichannelCorrelationService
from domain.entities import ChannelSignal, CorrelationMatch

client = TestClient(rest_server.app)
_HANDLER_HEADERS = {"X-API-Key": "dev-handler-key"}


class _FakeChannelSignalRepository:
    def __init__(self, matches: list[CorrelationMatch] | None = None):
        self._matches = matches or []
        self.recorded: list[ChannelSignal] = []

    def record(self, signal: ChannelSignal) -> None:
        self.recorded.append(signal)

    def find_matches(self, entities, exclude_channel, occurred_at, window_seconds):
        return self._matches


@pytest.fixture(autouse=True)
def _use_fake_channel_signal_repository(monkeypatch):
    fake_repo = _FakeChannelSignalRepository()
    monkeypatch.setattr(rest_server, "correlation_service", MultichannelCorrelationService(fake_repo))
    return fake_repo


def test_records_sms_signal_and_returns_no_matches_on_first_sighting():
    response = client.post(
        "/api/v1/correlate",
        json={"channel": "sms", "text": "010-1234-5678로 대출 승인 문자입니다"},
        headers=_HANDLER_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == []
    assert body["risk_boost"] == 0


def test_invalid_channel_is_rejected_with_422():
    response = client.post(
        "/api/v1/correlate", json={"channel": "fax", "text": "무관한 텍스트"}, headers=_HANDLER_HEADERS
    )

    assert response.status_code == 422


def test_missing_api_key_is_rejected_with_401():
    response = client.post("/api/v1/correlate", json={"channel": "sms", "text": "무관한 텍스트"})

    assert response.status_code == 401
