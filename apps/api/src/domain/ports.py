# domain 계층의 포트(인터페이스). "어떻게 판별/저장하는가"의 구체 구현(음향 특징 휴리스틱,
# mcp-server HTTP 호출, 인메모리 저장소 등)은 infrastructure에 맡기고, application은
# 이 인터페이스에만 의존한다.

from datetime import datetime
from typing import Protocol

from .deepvoice import DeepvoiceVerdict
from .entities import CallAnalysisResult, StatsSummary
from .identity_verification import CallVerificationRecord, GuardianNotification


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


class IdentityVerificationPort(Protocol):
    """역방향 신원확인 POC: 국민이 입력한 코드를 verify-worker(/api/v1/verify)에 넘겨
    검증하는 포트. 반환값은 verify-worker REST 응답 그대로의 dict — CallAnalysisPort와
    동일한 패턴. verify-worker는 실제 모바일신분증과 연동하지 않는 모의 시제품이다."""

    def verify(self, code: str, client_key: str | None = None) -> dict:
        """client_key는 국민 쪽 클라이언트 IP — verify-worker가 자기 쪽 실패 횟수 제한을
        api의 IP 하나가 아니라 실제 클라이언트별로 세도록 넘긴다. verify-worker가 제한에 걸어
        429를 돌려주면 예외 대신 그 본문(reason=rate_limited)을 그대로 돌려준다."""
        ...


class GuardianNotificationPort(Protocol):
    """신원확인 결과가 "확인 불가"일 때 보호자 알림(mock)을 남기는 포트."""

    def notify(self, call_id: str, reason: str) -> GuardianNotification: ...


class CallVerificationLogPort(Protocol):
    """통화별 신원확인 결과 저장소. 감사증적 테이블(call_analysis_results)은 append-only
    트리거로 UPDATE가 막혀 있어서, 판정 결과에 컬럼을 덧붙이지 않고 call_id로 묶이는 별도
    저장소로 분리했다(현재는 인메모리)."""

    def add(self, record: CallVerificationRecord) -> None: ...
    def list_for_call(self, call_id: str) -> list[CallVerificationRecord]: ...


class FailedAttemptStorePort(Protocol):
    """역방향 신원확인: 클라이언트별 검증 실패 시각 기록(무차별 대입 방어, domain/
    identity_verification.py RateLimitPolicy)."""

    def record_failure(self, client_key: str, at: datetime) -> None: ...

    def count_failures_since(self, client_key: str, since: datetime) -> int: ...


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
