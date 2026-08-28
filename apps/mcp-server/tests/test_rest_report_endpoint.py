# POST /api/v1/reports는 submit_report MCP 툴(server.py)과 같은 응답 형식을
# serialize_report(dto.py)로 공유한다. 여기서는 REST 어댑터 배선(라우팅, pydantic
# 검증)만 확인한다 — 채널 분기/영속화 로직 자체는 test_report_submission.py에서
# ReportSubmissionService 단위로 이미 검증한다.

from fastapi.testclient import TestClient

from rest_server import app

client = TestClient(app)


def test_high_risk_report_is_submitted_via_rest():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "검찰 사칭 통화", "risk_level": "high"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["channel"] == "auto"
    assert body["report_id"]


def test_non_high_risk_report_uses_manual_channel():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "경미한 의심", "risk_level": "low"}
    )

    assert response.status_code == 200
    assert response.json()["channel"] == "manual"


def test_invalid_risk_level_is_rejected_with_422():
    response = client.post(
        "/api/v1/reports", json={"case_summary": "알 수 없는 등급", "risk_level": "critical"}
    )

    assert response.status_code == 422
