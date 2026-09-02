# POST /api/v1/correlate 라우팅/인증/직렬화만 확인한다 — 실제 상관관계 매칭 로직은
# test_multichannel_correlation_service.py, postgres 연동은
# test_postgres_channel_signal_repository.py에서 이미 검증한다. test_rest_report_endpoint.py와
# 같은 이유로 postgres 없이 돌 수 있도록 가짜 저장소로 바꿔치기한다.

import datetime

import pytest
from fastapi.testclient import TestClient

import rest_server
from application.services import MultichannelCorrelationService
from domain.entities import Channel, ChannelSignal, CorrelationMatch, EntityType

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


def test_pre_extracted_entities_are_used_instead_of_text():
    """apps/api는 N-03 마스킹 전 원문을 이 서비스로 보내지 않는다 — 직접 추출한
    entities만 보낸다(docs/design.md 7장 참고)."""
    response = client.post(
        "/api/v1/correlate",
        json={
            "channel": "call",
            "entities": [{"entity_type": "phone", "value": "01012345678"}],
            "context_excerpt": "[전화번호]로 다시 연락드리겠습니다",
        },
        headers=_HANDLER_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["matches"] == []


def test_invalid_entity_type_is_rejected_with_422():
    response = client.post(
        "/api/v1/correlate",
        json={"channel": "call", "entities": [{"entity_type": "email_address", "value": "x@example.com"}]},
        headers=_HANDLER_HEADERS,
    )

    assert response.status_code == 422


def test_missing_text_and_entities_is_rejected_with_422():
    response = client.post("/api/v1/correlate", json={"channel": "call"}, headers=_HANDLER_HEADERS)

    assert response.status_code == 422


def test_current_risk_score_returns_updated_score_and_level(monkeypatch):
    match = CorrelationMatch(
        EntityType.PHONE, "01012345678", Channel.SMS, datetime.datetime.now(datetime.timezone.utc), "발췌"
    )
    fake_repo = _FakeChannelSignalRepository(matches=[match])
    monkeypatch.setattr(rest_server, "correlation_service", MultichannelCorrelationService(fake_repo))

    response = client.post(
        "/api/v1/correlate",
        json={
            "channel": "call",
            "entities": [{"entity_type": "phone", "value": "01012345678"}],
            "current_risk_score": 35,
        },
        headers=_HANDLER_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["risk_boost"] == 15
    assert body["updated_risk_score"] == 50
    assert body["updated_risk_level"] == "medium"
