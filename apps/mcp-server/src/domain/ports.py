# domain 계층의 포트(인터페이스). "어떻게 저장하는가"/"어떻게 판단하는가"의 구체 구현은
# infrastructure에 맡기고, application은 이 인터페이스에만 의존한다.

from typing import Protocol

from .entities import CallAnalysisResult, ReportRecord


class ReportRepositoryPort(Protocol):
    def add(self, record: ReportRecord) -> None: ...
    def list_recent(self, limit: int) -> list[ReportRecord]: ...


class CallAnalysisPort(Protocol):
    """F-01/F-02/F-05: 통화/문자 텍스트를 받아 패턴탐지+위험도점수+판정근거를 한 번에
    산출한다. 이 인터페이스 덕분에 구현체를 키워드 규칙(v1)에서 LLM(v2)으로 바꿔도
    server.py/rest_server.py, application/services.py의 CallAnalysisService는
    그대로 유지된다 (F-04의 FraudCaseSearchPort와 동일한 목적)."""

    def analyze(self, transcript: str) -> CallAnalysisResult: ...
