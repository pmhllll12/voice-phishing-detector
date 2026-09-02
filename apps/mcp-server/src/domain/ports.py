# domain 계층의 포트(인터페이스). "어떻게 저장하는가"/"어떻게 판단하는가"의 구체 구현은
# infrastructure에 맡기고, application은 이 인터페이스에만 의존한다.

from datetime import datetime
from typing import Protocol

from .entities import CallAnalysisResult, Channel, ChannelSignal, CorrelationMatch, ExtractedEntity, ReportRecord, SimilarCase


class ReportRepositoryPort(Protocol):
    def add(self, record: ReportRecord) -> None: ...
    def list_recent(self, limit: int) -> list[ReportRecord]: ...


class CallAnalysisPort(Protocol):
    """F-01/F-02/F-05: 통화/문자 텍스트를 받아 패턴탐지+위험도점수+판정근거를 한 번에
    산출한다. 이 인터페이스 덕분에 구현체를 키워드 규칙(v1)에서 LLM(v2)으로 바꿔도
    server.py/rest_server.py, application/services.py의 CallAnalysisService는
    그대로 유지된다 (F-04의 FraudCaseSearchPort와 동일한 목적)."""

    def analyze(self, transcript: str) -> CallAnalysisResult: ...


class FraudCaseSearchPort(Protocol):
    """F-04: rag-worker(/api/v1/similar-cases)에서 유사 사기 사례를 검색한다.
    CallAnalysisService가 판정 근거(F-05)에 결합할 때 쓰는 포트 — lookup_fraud_pattern_db
    MCP 툴이 같은 rag-worker를 부르는 것과는 별개 경로다(server.py 참고)."""

    def search(self, transcript: str, top_k: int) -> list[SimilarCase]: ...


class ChannelSignalRepositoryPort(Protocol):
    """우선순위 2(크로스채널 상관관계 탐지): 채널 이벤트(통화/문자/이메일)에서 추출된
    엔티티를 저장하고, 다른 채널에서 같은 엔티티가 시간 윈도우 안에 등장했는지 조회한다."""

    def record(self, signal: ChannelSignal) -> None: ...

    def find_matches(
        self,
        entities: list[ExtractedEntity],
        exclude_channel: Channel,
        occurred_at: datetime,
        window_seconds: int,
    ) -> list[CorrelationMatch]:
        """entities 중 하나라도 exclude_channel이 아닌 다른 채널에, occurred_at 기준
        ±window_seconds 이내에 기록된 적이 있으면 그 매치들을 반환한다."""
        ...


class ThreatIntelligencePort(Protocol):
    """우선순위 2(선택 항목): 문자/이메일 속 URL을 외부 위협 인텔리전스(Google Safe
    Browsing)와 대조한다. MultichannelCorrelationService가 크로스채널 상관관계 점수의
    한 요소로 결합할 때 쓰는 포트 — FraudCaseSearchPort와 같은 패턴으로, 없어도(None)
    상관관계 탐지 자체는 정상 동작한다(있으면 근거를 더 풍부하게 하는 선택적 의존)."""

    def check_urls(self, urls: list[str]) -> list[str]:
        """urls 중 악성으로 확인된 것만 골라 반환한다(순서 무관, 부분집합)."""
        ...
