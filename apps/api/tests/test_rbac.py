# N-02 접근통제(RBAC) 테스트. 두 계층을 검증한다:
#   1) domain/entities.py의 role_satisfies — 순수 함수, 계층 구조(admin ⊇ handler ⊇ viewer)
#   2) infrastructure/adapters/api_key_role_auth.py의 require_role dependency가 실제로
#      src/main.py 라우트에 배선되어 401/403/200 경로를 만들어내는지 (TestClient)
#
# FastAPI dependency는 라우트 핸들러 본문 실행 전에 평가되므로, 인증/인가 실패(401/403)
# 테스트는 실제 postgres/mcp-server 연결 없이도 항상 통과한다 — mocking이 필요한 건 실제로
# 핸들러 본문까지 도달하는 200 성공 경로뿐이다(test_ready_endpoint.py와 동일하게
# monkeypatch로 다운스트림을 페이크로 바꾼다).

import datetime

from fastapi.testclient import TestClient

import src.main as main
from src.domain.entities import CallAnalysisResult, Role, RiskLevel, role_satisfies
from src.infrastructure.adapters.api_key_role_auth import API_KEYS
from src.main import app

client = TestClient(app)

VIEWER_KEY = next(key for key, role in API_KEYS.items() if role == Role.VIEWER)
HANDLER_KEY = next(key for key, role in API_KEYS.items() if role == Role.HANDLER)
ADMIN_KEY = next(key for key, role in API_KEYS.items() if role == Role.ADMIN)


def test_role_hierarchy_admin_covers_handler_and_viewer():
    assert role_satisfies(Role.ADMIN, Role.HANDLER)
    assert role_satisfies(Role.ADMIN, Role.VIEWER)
    assert role_satisfies(Role.HANDLER, Role.VIEWER)


def test_role_hierarchy_lower_role_does_not_cover_higher():
    assert not role_satisfies(Role.VIEWER, Role.HANDLER)
    assert not role_satisfies(Role.HANDLER, Role.ADMIN)
    assert not role_satisfies(Role.VIEWER, Role.ADMIN)


def test_missing_api_key_is_rejected_with_401():
    response = client.get("/api/v1/calls")
    assert response.status_code == 401


def test_unknown_api_key_is_rejected_with_401():
    response = client.get("/api/v1/calls", headers={"X-API-Key": "not-a-real-key"})
    assert response.status_code == 401


def test_viewer_key_can_read_viewer_endpoint(monkeypatch):
    monkeypatch.setattr(main.call_log_query_service, "list_recent", lambda limit: [])

    response = client.get("/api/v1/calls", headers={"X-API-Key": VIEWER_KEY})

    assert response.status_code == 200


def test_viewer_key_is_rejected_with_403_on_handler_endpoint():
    """조회(VIEWER) 키로 처리(HANDLER) 행위를 시도하면 인증은 통과하되(키 자체는 유효)
    권한 부족으로 403이어야 한다 — 401(인증 실패)과 구분되는 것이 핵심."""
    response = client.post(
        "/api/v1/calls/analyze",
        json={"transcript": "안녕하세요"},
        headers={"X-API-Key": VIEWER_KEY},
    )
    assert response.status_code == 403


def test_handler_key_reaches_handler_endpoint_handler(monkeypatch):
    async def _fake_execute(transcript: str, channel: str = "call", occurred_at=None) -> CallAnalysisResult:
        return CallAnalysisResult(
            call_id="fake-call-id",
            raw_transcript=transcript,
            masked_transcript=transcript,
            risk_score=10,
            risk_level=RiskLevel.LOW,
            detected_patterns=[],
            explanation_summary="위험도 낮음",
            explanation="특이사항 없음",
            analyzed_at=datetime.datetime.now(datetime.timezone.utc),
            similar_cases=[],
        )

    monkeypatch.setattr(main.analyze_call_service, "execute", _fake_execute)

    response = client.post(
        "/api/v1/calls/analyze",
        json={"transcript": "안녕하세요"},
        headers={"X-API-Key": HANDLER_KEY},
    )

    assert response.status_code == 200
    assert response.json()["call_id"] == "fake-call-id"


def test_raw_transcript_hidden_from_handler_but_shown_to_admin(monkeypatch):
    """N-02 x N-03: masked_transcript는 누구나 보지만, raw_transcript(원문)는 ADMIN
    권한에서만 응답에 포함돼야 한다(domain/entities.py CallAnalysisResult, main.py
    _serialize_call_result 참고)."""

    async def _fake_execute(transcript: str, channel: str = "call", occurred_at=None) -> CallAnalysisResult:
        return CallAnalysisResult(
            call_id="fake-call-id",
            raw_transcript="검찰청인데 010-1234-5678로 전화드렸습니다",
            masked_transcript="검찰청인데 [전화번호]로 전화드렸습니다",
            risk_score=10,
            risk_level=RiskLevel.LOW,
            detected_patterns=[],
            explanation_summary="위험도 낮음",
            explanation="특이사항 없음",
            analyzed_at=datetime.datetime.now(datetime.timezone.utc),
            similar_cases=[],
        )

    monkeypatch.setattr(main.analyze_call_service, "execute", _fake_execute)

    handler_response = client.post(
        "/api/v1/calls/analyze", json={"transcript": "x"}, headers={"X-API-Key": HANDLER_KEY}
    )
    admin_response = client.post(
        "/api/v1/calls/analyze", json={"transcript": "x"}, headers={"X-API-Key": ADMIN_KEY}
    )

    assert handler_response.json()["masked_transcript"] == "검찰청인데 [전화번호]로 전화드렸습니다"
    assert "raw_transcript" not in handler_response.json()

    assert admin_response.json()["masked_transcript"] == "검찰청인데 [전화번호]로 전화드렸습니다"
    assert admin_response.json()["raw_transcript"] == "검찰청인데 010-1234-5678로 전화드렸습니다"


def test_admin_key_satisfies_both_viewer_and_handler_endpoints(monkeypatch):
    monkeypatch.setattr(main.call_log_query_service, "list_recent", lambda limit: [])

    response = client.get("/api/v1/calls", headers={"X-API-Key": ADMIN_KEY})

    assert response.status_code == 200


def test_health_ready_metrics_do_not_require_api_key(monkeypatch):
    monkeypatch.setattr(main, "_check_mcp_server_ready", lambda: {"status": "ok", "detail": "x"})
    monkeypatch.setattr(main, "_check_database_ready", lambda: {"status": "ok", "detail": "x"})
    monkeypatch.setattr(main, "_check_stt_worker_ready", lambda: {"status": "ok", "detail": "x"})

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/metrics").status_code == 200
