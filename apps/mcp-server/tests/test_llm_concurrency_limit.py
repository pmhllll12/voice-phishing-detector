# N-05 동시성 SLA 대응(2026-09-01) 회귀 가드 — rest_server.py의 /api/v1/analyze가
# run_in_threadpool + asyncio.Semaphore(LLM_MAX_CONCURRENCY)로 동시 실행 개수를
# 실제로 제한하는지 확인한다. GPU/Ollama 실측 결과(지연시간 개선 정도)는 이 단위
# 테스트로는 볼 수 없다 — 그건 docs/test-plan.md N-05 절의 실측 부하테스트가 담당하고,
# 여기서는 "제한 메커니즘 자체가 작동하는가"만 빠르게(실제 LLM 호출 없이) 검증한다.
#
# TestClient(스레드 여러 개로 동시 호출)는 내부 포털이 동시 호출용으로 설계돼있지
# 않아 실제로 교착 상태에 빠지는 걸 겪었다 — 그래서 FastAPI 라우팅을 거치지 않고
# `analyze()` 코루틴을 asyncio.gather로 직접 동시 실행한다(Depends는 함수 기본값
# 메커니즘일 뿐이라 직접 호출 시엔 인자로 넘기면 그만이다).

import asyncio
import threading
import time

import pytest

import rest_server
from domain.entities import Role


class _ConcurrencyTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._current = 0
        self.max_seen = 0

    def slow_execute(self, transcript: str, channel=None):
        with self._lock:
            self._current += 1
            self.max_seen = max(self.max_seen, self._current)
        try:
            time.sleep(0.2)
            return rest_server._rule_based_adapter.analyze(transcript)
        finally:
            with self._lock:
                self._current -= 1


@pytest.fixture
def tracker(monkeypatch):
    t = _ConcurrencyTracker()
    monkeypatch.setattr(rest_server.call_analysis_service, "execute", t.slow_execute)
    yield t


def _call_analyze_n_times_concurrently(n: int) -> list:
    async def run_all():
        return await asyncio.gather(
            *[
                rest_server.analyze(rest_server.AnalyzeRequest(transcript="테스트 통화 내용"), _role=Role.HANDLER)
                for _ in range(n)
            ]
        )

    return asyncio.run(run_all())


def test_concurrent_requests_are_limited_and_all_succeed(tracker):
    # 두 검증(동시성 제한 + 전체 성공)을 한 테스트로 합쳤다 — asyncio.Semaphore는
    # 처음 쓰인 이벤트 루프에 바인딩되는데, rest_server._llm_semaphore는 모듈
    # 임포트 시 한 번만 생성되는 전역 객체라 테스트 함수마다 asyncio.run()으로 새
    # 루프를 돌리면 두 번째 테스트에서 "다른 이벤트 루프에 바인딩됨" 에러가 난다
    # (실제로 겪음 — 운영에서는 uvicorn이 프로세스 생애주기 내내 루프 하나만 쓰므로
    # 문제되지 않는다. 이 프로세스 안에서 asyncio.run()을 두 번 이상 부르는 테스트
    # 환경에서만 나타나는 제약이다).
    results = _call_analyze_n_times_concurrently(6)

    limit = rest_server.LLM_MAX_CONCURRENCY
    assert tracker.max_seen <= limit, f"동시 실행 개수가 세마포어 한도({limit})를 넘음: {tracker.max_seen}"
    assert tracker.max_seen >= limit, "세마포어 한도까지는 실제로 병렬 실행돼야 한다(스레드풀 위임 확인)"
    assert len(results) == 6
    assert all("risk_score" in r for r in results)
