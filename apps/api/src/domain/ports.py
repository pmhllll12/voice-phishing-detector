# domain 계층의 포트(인터페이스). "어떻게 판별/저장하는가"의 구체 구현(음향 특징 휴리스틱,
# mcp-server HTTP 호출, 인메모리 저장소 등)은 infrastructure에 맡기고, application은
# 이 인터페이스에만 의존한다.

from typing import Protocol

from .deepvoice import DeepvoiceVerdict
from .entities import CallAnalysisResult, StatsSummary


class DeepvoiceDetectionPort(Protocol):
    def analyze(self, audio_bytes: bytes) -> DeepvoiceVerdict: ...


class CallAnalysisPort(Protocol):
    """F-01/F-02/F-05 판정을 mcp-server(analyze_call_pattern)에 위임하는 포트.
    반환값은 mcp-server REST 응답 그대로의 dict — application 계층에서 도메인 모델로 매핑한다.
    channel(SMS/email 실채널 연동): mcp-server가 channel별로 크로스채널 상관관계를
    올바른 채널에 기록하도록 전달한다(기본값 "call"은 기존 호출부와 하위호환)."""

    def analyze(self, transcript: str, channel: str = "call") -> dict: ...


class TranscriptionPort(Protocol):
    """F-05 모바일 실시간 감지: 오디오 청크를 stt-worker(/api/v1/transcribe)에 넘겨
    텍스트로 변환하는 포트."""

    def transcribe(self, audio_bytes: bytes) -> str: ...


class CallLogPort(Protocol):
    """N-01 감사증적(현재는 인메모리) + F-06 대시보드 조회용 저장소 포트."""

    def add(self, result: CallAnalysisResult) -> None: ...
    def list_recent(self, limit: int) -> list[CallAnalysisResult]: ...
    def stats_summary(self) -> StatsSummary: ...


class ReportPort(Protocol):
    """F-07 신고 접수(mock)를 mcp-server(submit_report)에 위임하는 포트.
    반환값은 mcp-server REST 응답 그대로의 dict — CallAnalysisPort와 동일한 패턴."""

    def submit(self, case_summary: str, risk_level: str) -> dict: ...


class MultichannelCorrelationPort(Protocol):
    """우선순위 2(크로스채널 상관관계 탐지): mcp-server(/api/v1/correlate)에 위임하는
    포트. entities는 마스킹 "전" 원문(raw_transcript)에서 이 계층이 직접 추출한
    값만 담는다 — 원문 자체는 mcp-server로 보내지 않는다(N-03과의 상호작용,
    docs/design.md 7장 참고). 반환값은 mcp-server REST 응답 그대로의 dict —
    CallAnalysisPort와 동일한 패턴."""

    def correlate(
        self,
        channel: str,
        entities: list[dict],
        occurred_at: str,
        context_excerpt: str,
        current_risk_score: int,
        source_ref: str | None = None,
    ) -> dict: ...
