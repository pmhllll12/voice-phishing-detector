# N-01 감사증적의 아주 단순한 v1 — 프로세스 메모리에만 쌓이고 재시작하면 사라진다.
# domain/ports.py의 ReportRepositoryPort를 구현한다. apps/api의
# InMemoryCallLogRepository와 동일한 패턴/한계 (TODO: postgres로 교체).

from domain.entities import ReportRecord


class InMemoryReportRepository:
    def __init__(self):
        self._records: list[ReportRecord] = []

    def add(self, record: ReportRecord) -> None:
        self._records.append(record)

    def list_recent(self, limit: int) -> list[ReportRecord]:
        return list(reversed(self._records[-limit:]))
