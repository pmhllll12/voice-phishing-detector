# 우선순위 2(SMS/email 실채널 연동, email만 실제 구현) — EmailIngestionService가
# EmailSourcePort로 받은 메일을 EmailAnalysisSinkPort(apps/api 경유, channel=EMAIL)에
# 올바르게 넘기고 처리 완료 표시까지 하는지 확인한다. 실제 Gmail API 연동은
# test_gmail_email_source_adapter.py, apps/api HTTP 어댑터 자체는
# test_api_email_analysis_adapter.py, F-01/F-02/F-05 판정 로직 자체는 다른 테스트에서
# 이미 검증했다 — 여기서는 오케스트레이션만 본다.

import datetime

from application.services import EmailIngestionService
from domain.entities import Channel, EmailMessage

_RECEIVED_AT = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.timezone.utc)

_HIGH_RISK_RESPONSE = {
    "call_id": "call-1",
    "risk_score": 80,
    "risk_level": "high",
    "explanation_summary": "고위험 등급 (위험도 80점)",
    "channel": "email",
}


class _FakeEmailSource:
    def __init__(self, emails: list[EmailMessage]):
        self._emails = emails
        self.marked_processed: list[str] = []

    def fetch_new_emails(self) -> list[EmailMessage]:
        return self._emails

    def mark_processed(self, message_id: str) -> None:
        self.marked_processed.append(message_id)


class _FakeAnalysisSink:
    def __init__(self, response: dict | None = None, raise_for: set[str] | None = None):
        self._response = response or dict(_HIGH_RISK_RESPONSE)
        self._raise_for = raise_for or set()
        self.received_calls: list[dict] = []

    def analyze(self, text: str, channel: Channel, occurred_at: datetime.datetime) -> dict:
        self.received_calls.append({"text": text, "channel": channel, "occurred_at": occurred_at})
        if text in self._raise_for:
            raise ConnectionError("apps/api 연결 실패(테스트 시뮬레이션)")
        return self._response


def test_poll_once_analyzes_each_email_as_email_channel_with_received_at():
    email = EmailMessage(
        message_id="msg-1",
        subject="[금융감독원] 계좌 정지 안내",
        body="귀하의 계좌가 정지될 예정이니 즉시 인증번호를 알려주세요.",
        received_at=_RECEIVED_AT,
    )
    email_source = _FakeEmailSource([email])
    analysis_sink = _FakeAnalysisSink()
    service = EmailIngestionService(email_source, analysis_sink)

    results = service.poll_once()

    assert len(results) == 1
    assert results[0][0] is email
    assert results[0][1]["risk_level"] == "high"
    assert analysis_sink.received_calls[0]["channel"] == Channel.EMAIL
    assert analysis_sink.received_calls[0]["occurred_at"] == _RECEIVED_AT
    assert email.subject in analysis_sink.received_calls[0]["text"]
    assert email.body in analysis_sink.received_calls[0]["text"]


def test_poll_once_marks_each_email_as_processed():
    emails = [
        EmailMessage("msg-1", "제목1", "본문1", _RECEIVED_AT),
        EmailMessage("msg-2", "제목2", "본문2", _RECEIVED_AT),
    ]
    email_source = _FakeEmailSource(emails)
    service = EmailIngestionService(email_source, _FakeAnalysisSink())

    service.poll_once()

    assert email_source.marked_processed == ["msg-1", "msg-2"]


def test_poll_once_with_no_new_emails_returns_empty_list():
    email_source = _FakeEmailSource([])
    service = EmailIngestionService(email_source, _FakeAnalysisSink())

    assert service.poll_once() == []


def test_poll_once_skips_mark_processed_when_analysis_fails_but_continues_others():
    """회귀 가드: 판정이 실패한 메일은 처리 완료 표시를 안 해야 다음 폴링에서
    재시도된다 — 다른 메일 처리는 계속 진행돼야 한다(기존 docstring이 주장만
    하고 실제로는 구현이 없던 부분, 2026-09-02 apps/api 경유 전환 때 같이 고침)."""
    broken_email = EmailMessage("broken", "제목", "본문", _RECEIVED_AT)
    ok_email = EmailMessage("ok", "제목2", "본문2", _RECEIVED_AT)
    email_source = _FakeEmailSource([broken_email, ok_email])
    analysis_sink = _FakeAnalysisSink(raise_for={"제목\n\n본문"})
    service = EmailIngestionService(email_source, analysis_sink)

    results = service.poll_once()

    assert [e.message_id for e, _ in results] == ["ok"]
    assert email_source.marked_processed == ["ok"]
