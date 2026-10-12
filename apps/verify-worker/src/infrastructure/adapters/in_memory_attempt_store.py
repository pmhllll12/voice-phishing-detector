# infrastructure 계층: FailedAttemptStorePort의 인메모리 슬라이딩 윈도우 구현.
#
# 클라이언트(IP)마다 실패 시각을 deque에 쌓고, 조회할 때 윈도우보다 오래된 시각을 앞에서부터
# 버린다. 프로세스 재시작 시 기록이 사라지고, 여러 워커/인스턴스 사이에서 공유되지 않는다
# (POC 범위 — 공유가 필요하면 같은 포트의 Redis 구현으로 바꾼다).
# 오래 조용한 클라이언트의 빈 deque는 조회 시에만 지워지므로, IP를 계속 바꾸는 대량 요청에는
# 메모리가 늘 수 있다(docs/poc-mobile-id.md 5장 한계).

import threading
from collections import defaultdict, deque
from datetime import datetime


class InMemoryFailedAttemptStore:
    def __init__(self):
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def record_failure(self, client_key: str, at: datetime) -> None:
        with self._lock:
            self._failures[client_key].append(at)

    def count_failures_since(self, client_key: str, since: datetime) -> int:
        with self._lock:
            times = self._failures.get(client_key)
            if not times:
                return 0
            while times and times[0] <= since:
                times.popleft()
            if not times:
                del self._failures[client_key]
                return 0
            return len(times)
