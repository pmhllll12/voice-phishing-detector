# /ready는 api의 실제 의존 서비스(mcp-server, stt-worker, postgres)를 확인한다 —
# src/main.py 상단 "_check_mcp_server_ready"/"_check_stt_worker_ready"/
# "_check_database_ready" 주석 참고. httpx.get과 call_log_repository.ping을
# monkeypatch해서 실제 네트워크/DB 호출 없이 성공/실패 경로를 검증한다.

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

import src.main as main
from src.main import _check_database_ready, _check_mcp_server_ready, _check_stt_worker_ready, app


class _FakeResponse:
    def raise_for_status(self):
        return None


@pytest.fixture(autouse=True)
def _database_ready_by_default(monkeypatch):
    """이 파일의 테스트는 mcp-server/stt-worker 시나리오에 집중한다 — 개별 테스트가
    직접 재정의하지 않는 한, database 체크는 항상 통과한 것으로 취급해 실제 postgres가
    떠 있지 않아도 이 파일이 통과하게 한다(postgres 연동 자체는
    test_postgres_call_log_repository.py에서 실제 DB로 검증한다)."""
    monkeypatch.setattr(main, "_check_database_ready", lambda: {"status": "ok", "detail": "postgres"})


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


def test_database_ready_when_reachable(monkeypatch):
    monkeypatch.setattr(main.call_log_repository, "ping", lambda: None)

    result = _check_database_ready()

    assert result["status"] == "ok"


def test_database_ready_when_unreachable(monkeypatch):
    def _raise():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(main.call_log_repository, "ping", _raise)

    result = _check_database_ready()

    assert result["status"] == "error"
    assert "OperationalError" in result["detail"]


def test_overall_ready_is_error_503_when_only_database_is_down(monkeypatch):
    """postgres는 analyze_call이 매번 쓰는 실제 의존 서비스라 stt-worker와 달리
    degraded가 아니라 503이어야 한다 (_check_database_ready 주석 참고). 이 테스트는
    autouse 픽스처가 항상 통과시키는 database 체크를 실제 구현으로 되돌린 뒤
    call_log_repository.ping만 실패시켜 진짜 실패 경로를 검증한다."""
    monkeypatch.setattr(httpx, "get", lambda url, timeout: _FakeResponse())
    monkeypatch.setattr(main, "_check_database_ready", _check_database_ready)

    def _raise():
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(main.call_log_repository, "ping", _raise)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["checks"]["database"]["status"] == "error"
    assert body["checks"]["mcp_server"]["status"] == "ok"
