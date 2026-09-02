# 우선순위 2(SMS/email 실채널 연동, email만 실제 구현) — EmailIngestionService가
# EmailSourcePort로 받은 메일을 CallAnalysisService(channel=EMAIL)에 올바르게 넘기고
# 처리 완료 표시까지 하는지 확인한다. 실제 Gmail API 연동은
# test_gmail_email_source_adapter.py, F-01/F-02/F-05 판정 로직 자체는 다른 테스트에서
# 이미 검증했다 — 여기서는 오케스트레이션만 본다.

import datetime

from application.services import CallAnalysisService, EmailIngestionService
from domain.entities import (
    CallAnalysisResult,
    Channel,
    DetectedPattern,
    EmailMessage,
    PatternCategory,
    PatternDetectionResult,
    RiskAssessment,
    RiskExplanation,
    RiskLevel,
)

_RECEIVED_AT = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.timezone.utc)


def _high_risk_result() -> CallAnalysisResult:
    detection = PatternDetectionResult(
        transcript="", detected_patterns=[DetectedPattern(category=PatternCategory.AUTHORITY_IMPERSONATION, matched_keywords=["금융감독원"])]
    )
    risk = RiskAssessment(score=80, level=RiskLevel.HIGH, breakdown=[])
    explanation = RiskExplanation(summary="고위험", reasons=["..."], narrative="고위험\n\n근거:\n- ...")
    return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)


class _FakeEmailSource:
    def __init__(self, emails: list[EmailMessage]):
        self._emails = emails
        self.marked_processed: list[str] = []

    def fetch_new_emails(self) -> list[EmailMessage]:
        return self._emails

    def mark_processed(self, message_id: str) -> None:
        self.marked_processed.append(message_id)


class _FakeCallAnalysisPort:
    def __init__(self, result: CallAnalysisResult):
        self._result = result

    def analyze(self, transcript: str) -> CallAnalysisResult:
        return self._result


class _RecordingCallAnalysisService(CallAnalysisService):
    """CallAnalysisService.execute()에 어떤 인자가 전달됐는지 기록만 하는 얇은 래퍼."""

    def __init__(self, result: CallAnalysisResult):
        super().__init__(_FakeCallAnalysisPort(result))
        self.received_calls: list[dict] = []

    def execute(self, transcript, channel=Channel.CALL, occurred_at=None) -> CallAnalysisResult:
        self.received_calls.append({"transcript": transcript, "channel": channel, "occurred_at": occurred_at})
        return super().execute(transcript, channel=channel, occurred_at=occurred_at)


def test_poll_once_analyzes_each_email_as_email_channel_with_received_at():
    email = EmailMessage(
        message_id="msg-1",
        subject="[금융감독원] 계좌 정지 안내",
        body="귀하의 계좌가 정지될 예정이니 즉시 인증번호를 알려주세요.",
        received_at=_RECEIVED_AT,
    )
    email_source = _FakeEmailSource([email])
    call_analysis_service = _RecordingCallAnalysisService(_high_risk_result())
    service = EmailIngestionService(email_source, call_analysis_service)

    results = service.poll_once()

    assert len(results) == 1
    assert results[0][0] is email
    assert results[0][1].risk.level == RiskLevel.HIGH
    assert call_analysis_service.received_calls[0]["channel"] == Channel.EMAIL
    assert call_analysis_service.received_calls[0]["occurred_at"] == _RECEIVED_AT
    assert email.subject in call_analysis_service.received_calls[0]["transcript"]
    assert email.body in call_analysis_service.received_calls[0]["transcript"]


def test_poll_once_marks_each_email_as_processed():
    emails = [
        EmailMessage("msg-1", "제목1", "본문1", _RECEIVED_AT),
        EmailMessage("msg-2", "제목2", "본문2", _RECEIVED_AT),
    ]
    email_source = _FakeEmailSource(emails)
    service = EmailIngestionService(email_source, _RecordingCallAnalysisService(_high_risk_result()))

    service.poll_once()

    assert email_source.marked_processed == ["msg-1", "msg-2"]


def test_poll_once_with_no_new_emails_returns_empty_list():
    email_source = _FakeEmailSource([])
    service = EmailIngestionService(email_source, _RecordingCallAnalysisService(_high_risk_result()))

    assert service.poll_once() == []
