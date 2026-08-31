# POST /api/v1/reports는 submit_report MCP 툴(server.py)과 같은 응답 형식을
# serialize_report(dto.py)로 공유한다. 여기서는 REST 어댑터 배선(라우팅, pydantic
# 검증)만 확인한다 — 채널 분기/영속화 로직 자체는 test_report_submission.py에서
# ReportSubmissionService 단위로 이미 검증한다.
#
# rest_server.report_submission_service는 기본적으로 postgres(PostgresReportRepository)에
# 연결되지만, 이 파일은 라우팅/검증만 확인하는 목적이라 실제 postgres가 떠 있을 필요가
# 없도록 인메모리 저장소로 바꿔치기한다 (postgres 연동 자체는
# tests/test_postgres_report_repository.py에서 실제 DB로 검증한다).

import pytest
from fastapi.testclient import TestClient

import rest_server
from application.services import ReportSubmissionService
from infrastructure.adapters.in_memory_report_repository import InMemoryReportRepository

client = TestClient(rest_server.app)
# N-02: /api/v1/reports는 HANDLER 이상 권한을 요구한다 — api_key_role_auth.py의
# DEFAULT_API_KEYS 중 handler 키.
_HANDLER_HEADERS = {"X-API-Key": "dev-handler-key"}


@pytest.fixture(autouse=True)
def _use_in_memory_report_repository(monkeypatch):
    monkeypatch.setattr(rest_server, "report_submission_service", ReportSubmissionService(InMemoryReportRepository()))


def test_high_risk_report_is_submitted_via_rest():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "검찰 사칭 통화", "risk_level": "high"}, headers=_HANDLER_HEADERS
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["channel"] == "auto"
    assert body["report_id"]


def test_non_high_risk_report_uses_manual_channel():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "경미한 의심", "risk_level": "low"}, headers=_HANDLER_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["channel"] == "manual"


def test_invalid_risk_level_is_rejected_with_422():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "알 수 없는 등급", "risk_level": "critical"}, headers=_HANDLER_HEADERS
    )

    assert response.status_code == 422


def test_missing_api_key_is_rejected_with_401():
    response = client.post("/api/v1/reports", json={"case_summary": "검찰 사칭 통화", "risk_level": "high"})

    assert response.status_code == 401
