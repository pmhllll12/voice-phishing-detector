# ApiEmailAnalysisAdapter 단위 테스트 — httpx.post를 monkeypatch해서 apps/api 없이
# 요청 구성/응답 반환만 검증한다.

import datetime

import httpx

from domain.entities import Channel
from infrastructure.adapters.api_email_analysis_adapter import ApiEmailAnalysisAdapter


class _FakeResponse:
    def __init__(self, json_body: dict):
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_posts_transcript_channel_and_occurred_at(monkeypatch):
    captured = {}

    def _fake_post(url, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _FakeResponse({"risk_score": 80, "risk_level": "high"})

    monkeypatch.setattr(httpx, "post", _fake_post)
    adapter = ApiEmailAnalysisAdapter(api_base_url="http://localhost:8000", api_key="dev-handler-key")
    occurred_at = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.timezone.utc)

    result = adapter.analyze("제목\n\n본문", Channel.EMAIL, occurred_at)

    assert result == {"risk_score": 80, "risk_level": "high"}
    assert captured["url"] == "http://localhost:8000/api/v1/calls/analyze"
    assert captured["json"] == {
        "transcript": "제목\n\n본문",
        "channel": "email",
        "occurred_at": "2026-09-02T09:00:00+00:00",
    }
    assert captured["headers"] == {"X-API-Key": "dev-handler-key"}


def test_raises_on_http_error(monkeypatch):
    def _fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _fake_post)
    adapter = ApiEmailAnalysisAdapter(api_base_url="http://localhost:8000", api_key="dev-handler-key")

    try:
        adapter.analyze("텍스트", Channel.EMAIL, datetime.datetime.now(datetime.timezone.utc))
        assert False, "예외가 발생해야 한다 — EmailIngestionService가 이걸 잡아서 그 메일만 건너뛴다"
    except httpx.ConnectError:
        pass
