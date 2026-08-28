# /ready는 api의 실제 의존 서비스(mcp-server, stt-worker)를 확인한다 — src/main.py 상단
# "_check_mcp_server_ready"/"_check_stt_worker_ready" 주석 참고. httpx.get을
# monkeypatch해서 실제 네트워크 호출 없이 성공/실패 경로를 검증한다.

import httpx
import pytest
from fastapi.testclient import TestClient

from src.main import _check_mcp_server_ready, _check_stt_worker_ready, app


class _FakeResponse:
    def raise_for_status(self):
        return None


def test_mcp_server_ready_when_reachable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _FakeResponse())

    result = _check_mcp_server_ready()

    assert result["status"] == "ok"


def test_mcp_server_ready_when_unreachable(monkeypatch):
    def _raise(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _raise)

    result = _check_mcp_server_ready()

    assert result["status"] == "error"
    assert "ConnectError" in result["detail"]


def test_stt_worker_ready_when_reachable(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _FakeResponse())

    result = _check_stt_worker_ready()

    assert result["status"] == "ok"


def test_stt_worker_ready_when_unreachable(monkeypatch):
    def _raise(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _raise)

    result = _check_stt_worker_ready()

    assert result["status"] == "error"
    assert "ConnectError" in result["detail"]


def test_overall_ready_is_degraded_not_503_when_only_stt_worker_is_down(monkeypatch):
    """텍스트 경로(analyze_call)는 stt-worker 없이도 동작하므로, stt-worker만
    다운됐을 때는 mcp_client_adapter처럼 503으로 막지 않고 degraded로만 표시해야 한다."""

    def _fake_get(url, timeout):
        if "8100" in url:
            return _FakeResponse()
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _fake_get)

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["stt_worker"]["status"] == "error"
    assert body["checks"]["mcp_server"]["status"] == "ok"


def test_overall_ready_is_error_503_when_mcp_server_is_down(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda url, timeout: (_ for _ in ()).throw(httpx.ConnectError("connection refused"))
    )

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
