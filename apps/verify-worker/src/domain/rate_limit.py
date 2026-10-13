# domain 계층: 확인 코드 무차별 대입 방어 규칙(외부 의존성 없음).
#
# 6자리 코드 공간은 10^6이다. TTL(기본 180초)과 일회용 처리만으로는 한 클라이언트가 짧은
# 시간에 코드를 계속 바꿔 넣는 것을 막지 못해서, 클라이언트별 "실패" 횟수를 슬라이딩 윈도우로
# 센다. 성공은 세지 않는다 — 정상 직원 확인이 다른 사람의 시도 횟수를 깎아 먹지 않게.
#
# 제한에 걸린 요청은 검증 자체를 하지 않고 rate_limited로 돌려보낸다(그 사이 맞는 코드를 넣어도
# 통과시키지 않음 — 그래야 제한이 대입 시도를 실제로 멈춘다). 제한으로 거절된 요청은 실패
# 횟수에 다시 더하지 않는다: "실패 N회"는 실제로 검증해서 틀린 횟수만 뜻한다.

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class RateLimitPolicy:
    max_failures: int = 5
    window_seconds: int = 600

    def __post_init__(self):
        if self.max_failures < 1 or self.window_seconds < 1:
            raise ValueError("max_failures와 window_seconds는 1 이상이어야 합니다.")

    def window_start(self, now: datetime) -> datetime:
        """지금부터 window_seconds 이전 — 이 시각 이후의 실패만 센다(슬라이딩 윈도우)."""
        return now - timedelta(seconds=self.window_seconds)

    def is_limited(self, recent_failures: int) -> bool:
        """윈도우 안의 실패가 이미 max_failures회면 이번 시도는 막는다(6번째 시도부터 거절)."""
        return recent_failures >= self.max_failures
