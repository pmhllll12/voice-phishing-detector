# N-01 감사증적의 인메모리 구현 — 프로세스 재시작 시 사라진다. domain/ports.py의
# CallLogPort를 구현한다. 실제 감사증적(재시작해도 안 사라지고, append-only가 DB 레벨로
# 강제됨)은 PostgresCallLogRepository를 쓴다 — 이 구현체는 이제 postgres 없이 빠르게
# 돌려야 하는 테스트 전용으로 남아있다.

from src.domain.entities import CallAnalysisResult, StatsSummary, compute_stats_summary


class InMemoryCallLogRepository:
    def __init__(self):
        self._records: list[CallAnalysisResult] = []

    def add(self, result: CallAnalysisResult) -> None:
        self._records.append(result)

    def list_recent(self, limit: int) -> list[CallAnalysisResult]:
        return list(reversed(self._records[-limit:]))

    def stats_summary(self) -> StatsSummary:
        return compute_stats_summary(self._records)
