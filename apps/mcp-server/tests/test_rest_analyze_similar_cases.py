# POST /api/v1/analyze가 F-04(유사사례) 결과를 similar_cases/explanation에 실제로
# 결합해서 내보내는지 REST 레벨에서 확인한다. httpx.post를 monkeypatch해서 실제
# rag-worker 네트워크 호출 없이 두 경로(검색 성공/실패)를 모두 검증한다 — 이 컨테이너에는
# rag-worker가 실제로 8200에 떠 있을 수 있어(run-voice-phishing-detector 스킬), 그
# 상태에 의존하지 않기 위함이다.

import httpx
from fastapi.testclient import TestClient

from rest_server import app

client = TestClient(app)

_HIGH_RISK_TRANSCRIPT = (
    "검찰청 수사관인데 귀하 계좌가 범죄에 연루되어 체포영장이 발부될 수 있습니다. "
    "지금 즉시 안전계좌로 이체하셔야 합니다."
)


class _FakeSimilarCasesResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "matches": [
                {
                    "case_id": "case-1",
                    "title": "검찰 사칭 안전계좌 편취",
                    "category": "authority_impersonation",
                    "summary": "검찰청을 사칭해 안전계좌로 이체를 유도한 사례",
                    "source_note": "경찰청 보도자료 요약",
                    "similarity": 0.87,
                }
            ]
        }


def test_analyze_includes_similar_cases_when_rag_worker_is_reachable(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: _FakeSimilarCasesResponse())

    response = client.post("/api/v1/analyze", json={"transcript": _HIGH_RISK_TRANSCRIPT})

    assert response.status_code == 200
    body = response.json()
    assert body["similar_cases"][0]["title"] == "검찰 사칭 안전계좌 편취"
    assert "검찰 사칭 안전계좌 편취" in body["explanation"]


def test_analyze_still_succeeds_when_rag_worker_is_unreachable(monkeypatch):
    def _raise(url, json, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)

    response = client.post("/api/v1/analyze", json={"transcript": _HIGH_RISK_TRANSCRIPT})

    assert response.status_code == 200
    body = response.json()
    assert body["similar_cases"] == []
    assert body["risk_level"] == "high"  # F-01/F-02는 rag-worker 없이도 정상 동작


def test_analyze_skips_search_for_benign_text(monkeypatch):
    # httpx.post는 CALL_ANALYSIS_BACKEND=llm일 때 Ollama 호출에도 쓰이므로(다른 테스트
    # 파일의 importlib.reload로 인해 이 프로세스에서 어떤 백엔드가 활성인지는 테스트
    # 실행 순서에 좌우된다), rag-worker 엔드포인트로 간 호출만 걸러서 확인한다.
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, json, timeout: calls.append(url) or _FakeSimilarCasesResponse())

    response = client.post("/api/v1/analyze", json={"transcript": "내일 회의 시간 확인차 연락드렸습니다."})

    assert response.status_code == 200
    assert response.json()["similar_cases"] == []
    assert not any("similar-cases" in url for url in calls)  # 위험 정황이 없으면 rag-worker를 아예 부르지 않는다
