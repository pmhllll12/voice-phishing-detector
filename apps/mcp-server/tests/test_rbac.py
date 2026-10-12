# N-02 접근통제(RBAC) 테스트 — apps/api/tests/test_rbac.py와 동일한 구조. mcp-server의
# /api/v1/analyze, /api/v1/reports를 HANDLER 이상 권한으로 보호하는지 확인한다.
# health/ready/metrics는 미인증이어야 한다(rest_server.py 상단 주석 참고).

import pytest
from fastapi.testclient import TestClient

import rest_server
from application.services import ReportSubmissionService
from domain.entities import Role, role_satisfies
from infrastructure.adapters.api_key_role_auth import API_KEYS
from infrastructure.adapters.in_memory_report_repository import InMemoryReportRepository

client = TestClient(rest_server.app)

VIEWER_KEY = next(key for key, role in API_KEYS.items() if role == Role.VIEWER)
HANDLER_KEY = next(key for key, role in API_KEYS.items() if role == Role.HANDLER)
ADMIN_KEY = next(key for key, role in API_KEYS.items() if role == Role.ADMIN)


@pytest.fixture(autouse=True)
def _use_in_memory_report_repository(monkeypatch):
    monkeypatch.setattr(rest_server, "report_submission_service", ReportSubmissionService(InMemoryReportRepository()))


def test_role_hierarchy_admin_covers_handler_and_viewer():
    assert role_satisfies(Role.ADMIN, Role.HANDLER)
    assert role_satisfies(Role.ADMIN, Role.VIEWER)
    assert role_satisfies(Role.HANDLER, Role.VIEWER)


def test_role_hierarchy_lower_role_does_not_cover_higher():
    assert not role_satisfies(Role.VIEWER, Role.HANDLER)
    assert not role_satisfies(Role.HANDLER, Role.ADMIN)


def test_missing_api_key_is_rejected_with_401():
    response = client.post("/api/v1/reports", json={"case_summary": "x", "risk_level": "high"})
    assert response.status_code == 401


def test_unknown_api_key_is_rejected_with_401():
    response = client.post(
        "/api/v1/reports",
        json={"case_summary": "x", "risk_level": "high"},
        headers={"X-API-Key": "not-a-real-key"},
    )
    assert response.status_code == 401


def test_viewer_key_is_rejected_with_403_on_handler_endpoint():
    """조회(VIEWER) 키로 처리(HANDLER) 행위를 시도하면 401이 아니라 403이어야 한다 —
    키 자체는 유효하지만 권한이 부족한 것과 키가 아예 무효한 것은 구분돼야 한다."""
    response = client.post(
        "/api/v1/reports",
        json={"case_summary": "x", "risk_level": "high"},
        headers={"X-API-Key": VIEWER_KEY},
    )
    assert response.status_code == 403


def test_handler_key_reaches_reports_endpoint():
    response = client.post(
        "/api/v1/reports",
        json={"case_summary": "검찰 사칭 통화", "risk_level": "high"},
        headers={"X-API-Key": HANDLER_KEY},
    )
    assert response.status_code == 200


def test_admin_key_also_reaches_reports_endpoint():
    response = client.post(
        "/api/v1/reports",
        json={"case_summary": "검찰 사칭 통화", "risk_level": "high"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert response.status_code == 200


def test_health_ready_metrics_do_not_require_api_key():
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 200
