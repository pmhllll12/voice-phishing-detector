# /ready는 api의 유일한 실제 의존 서비스(mcp-server)만 확인한다 — src/main.py 상단
# "_check_mcp_server_ready" 주석 참고. httpx.get을 monkeypatch해서 실제 네트워크
# 호출 없이 성공/실패 두 경로를 검증한다.

import httpx
import pytest

from src.main import _check_mcp_server_ready


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
