# GoogleSafeBrowsingAdapter 단위 테스트 — 실제 Google API를 호출하지 않고 httpx.post를
# monkeypatch해서 요청 구성/응답 파싱/실패 폴백만 검증한다. 실제 API 키로 검증하는 건
# 이 저장소 CI/로컬 테스트 범위 밖(키가 없으면 이 어댑터 자체를 안 만든다 — server.py 참고).

import httpx
import pytest

from infrastructure.adapters.google_safe_browsing_adapter import GoogleSafeBrowsingAdapter


class _FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 200):
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self) -> dict:
        return self._json_body


def test_returns_empty_list_for_empty_input():
    adapter = GoogleSafeBrowsingAdapter(api_key="dummy")

    assert adapter.check_urls([]) == []


def test_flags_urls_present_in_matches(monkeypatch):
    captured_request = {}

    def _fake_post(url, params, json, timeout):
        captured_request["url"] = url
        captured_request["params"] = params
        captured_request["json"] = json
        return _FakeResponse({"matches": [{"threatType": "SOCIAL_ENGINEERING", "threat": {"url": "http://evil.example.com/"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)
    adapter = GoogleSafeBrowsingAdapter(api_key="dummy-key")

    result = adapter.check_urls(["evil.example.com", "benign.example.com"])

    assert result == ["evil.example.com"]
    assert captured_request["params"] == {"key": "dummy-key"}
    entries = captured_request["json"]["threatInfo"]["threatEntries"]
    assert {"url": "http://evil.example.com/"} in entries
    assert {"url": "http://benign.example.com/"} in entries


def test_no_matches_returns_empty_list(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({}))
    adapter = GoogleSafeBrowsingAdapter(api_key="dummy")

    assert adapter.check_urls(["benign.example.com"]) == []


def test_http_error_falls_back_to_empty_list_without_raising(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    adapter = GoogleSafeBrowsingAdapter(api_key="dummy")

    assert adapter.check_urls(["example.com"]) == []


def test_non_200_status_falls_back_to_empty_list(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({}, status_code=403))
    adapter = GoogleSafeBrowsingAdapter(api_key="invalid-key")

    assert adapter.check_urls(["example.com"]) == []
