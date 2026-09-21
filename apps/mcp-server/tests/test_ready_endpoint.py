# /ready는 CALL_ANALYSIS_BACKEND=rule이면 Ollama를 아예 안 쓰므로 not_applicable을
# 반환해야 하고, llm 백엔드에서 Ollama가 죽어있으면 자동 폴백이 있으므로 error가
# 아니라 degraded여야 한다 — rest_server.py 상단 "_check_ollama_ready" 주석 참고.

import importlib

import httpx
import pytest


class _FakeResponse:
    def raise_for_status(self):
        return None


def _reload_rest_server(monkeypatch, backend: str):
    monkeypatch.setenv("CALL_ANALYSIS_BACKEND", backend)
    import rest_server

    return importlib.reload(rest_server)


def test_ollama_ready_when_backend_is_rule(monkeypatch):
    rest_server = _reload_rest_server(monkeypatch, "rule")

    result = rest_server._check_ollama_ready()

    assert result["status"] == "not_applicable"


def test_ollama_ready_when_reachable(monkeypatch):
    rest_server = _reload_rest_server(monkeypatch, "llm")
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _FakeResponse())

    result = rest_server._check_ollama_ready()

    assert result["status"] == "ok"


def test_ollama_ready_when_unreachable_is_degraded_not_error(monkeypatch):
    rest_server = _reload_rest_server(monkeypatch, "llm")

    def _raise(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _raise)

    check = rest_server._check_ollama_ready()
    assert check["status"] == "error"

    response = rest_server.ready()
    assert response.status_code == 200  # 폴백 가능하므로 503이 아니라 200 + degraded
