# N-01 감사증적의 인메모리 구현 — 프로세스 재시작 시 사라진다. domain/ports.py의
# ReportRepositoryPort를 구현한다. 실제 감사증적은 PostgresReportRepository를 쓴다 —
# 이 구현체는 postgres 없이 빠르게 돌려야 하는 테스트 전용으로 남아있다.

from domain.entities import ReportRecord


class InMemoryReportRepository:
    def __init__(self):
        self._records: list[ReportRecord] = []

    def add(self, record: ReportRecord) -> None:
        self._records.append(record)

    def list_recent(self, limit: int) -> list[ReportRecord]:
        return list(reversed(self._records[-limit:]))
