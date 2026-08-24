# domain 계층의 포트(인터페이스). "어떻게 저장하는가"의 구체 구현(지금은 인메모리,
# 나중에는 postgres)은 infrastructure에 맡기고, application은 이 인터페이스에만 의존한다.

from typing import Protocol

from .entities import ReportRecord


class ReportRepositoryPort(Protocol):
    def add(self, record: ReportRecord) -> None: ...
    def list_recent(self, limit: int) -> list[ReportRecord]: ...
