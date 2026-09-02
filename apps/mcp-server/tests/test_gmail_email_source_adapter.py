# GmailEmailSourceAdapter 단위 테스트 — 실제 Gmail API를 호출하지 않고 googleapiclient의
# 체이닝 패턴(.users().messages().list(...).execute())을 흉내 낸 가짜 service로 검증한다.
# build_gmail_service()(OAuth 토큰 로드/갱신, google-auth-oauthlib 필요)는 이 저장소
# 테스트 의존성에 없는 별도 requirements-gmail.txt 패키지를 쓰므로 여기서 테스트하지
# 않는다 — 실제 검증은 scripts/gmail_oauth_setup.py로 토큰을 받은 뒤 수동으로 한다
# (README "Gmail 이메일 채널 연동" 절 참고).

import base64
import datetime

from infrastructure.adapters.gmail_email_source_adapter import GmailEmailSourceAdapter, _find_body, _parse_message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeMessagesResource:
    def __init__(self, list_response, get_responses):
        self._list_response = list_response
        self._get_responses = get_responses
        self.modify_calls: list[tuple[str, dict]] = []

    def list(self, userId, q, labelIds):
        return _FakeRequest(self._list_response)

    def get(self, userId, id, format):
        return _FakeRequest(self._get_responses[id])

    def modify(self, userId, id, body):
        self.modify_calls.append((id, body))
        return _FakeRequest({})


class _FakeUsers:
    def __init__(self, messages_resource):
        self._messages_resource = messages_resource

    def messages(self):
        return self._messages_resource


class _FakeGmailService:
    def __init__(self, messages_resource):
        self._messages_resource = messages_resource

    def users(self):
        return _FakeUsers(self._messages_resource)


# --- _parse_message / _find_body: 순수 파싱 로직 ---


def test_parses_simple_plain_text_message():
    raw = {
        "id": "msg-1",
        "internalDate": "1756789200000",  # 2026-09-02T02:00:00Z 근방(임의값, 존재만 확인)
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "[금융감독원] 계좌 정지 안내"}],
            "body": {"data": _b64("귀하의 계좌가 정지될 예정입니다.")},
        },
    }

    message_id, subject, body, received_at = _parse_message(raw)

    assert message_id == "msg-1"
    assert subject == "[금융감독원] 계좌 정지 안내"
    assert body == "귀하의 계좌가 정지될 예정입니다."
    assert isinstance(received_at, datetime.datetime)


def test_parses_multipart_message_preferring_text_plain():
    raw = {
        "id": "msg-2",
        "internalDate": "0",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "Subject", "value": "안내"}],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("일반 텍스트 본문")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML 본문</p>")}},
            ],
        },
    }

    _, _, body, _ = _parse_message(raw)

    assert body == "일반 텍스트 본문"


def test_falls_back_to_html_when_no_plain_text_part():
    raw = {
        "id": "msg-3",
        "internalDate": "0",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [],
            "parts": [{"mimeType": "text/html", "body": {"data": _b64("<b>굵게</b> 강조")}}],
        },
    }

    _, _, body, _ = _parse_message(raw)

    assert "굵게" in body
    assert "강조" in body
    assert "<b>" not in body


def test_missing_subject_header_defaults_to_placeholder():
    raw = {"id": "msg-4", "internalDate": "0", "payload": {"headers": [], "body": {"data": _b64("본문만 있음")}}}

    _, subject, _, _ = _parse_message(raw)

    assert subject == "(제목 없음)"


def test_find_body_returns_empty_string_when_no_body_data():
    assert _find_body({"headers": []}) == ""


# --- GmailEmailSourceAdapter: 목록 조회 -> 개별 조회 -> 처리 완료 표시 ---


def test_fetch_new_emails_lists_and_fetches_each_unread_message():
    list_response = {"messages": [{"id": "msg-1"}, {"id": "msg-2"}]}
    get_responses = {
        "msg-1": {
            "id": "msg-1",
            "internalDate": "0",
            "payload": {"headers": [{"name": "Subject", "value": "제목1"}], "body": {"data": _b64("본문1")}},
        },
        "msg-2": {
            "id": "msg-2",
            "internalDate": "0",
            "payload": {"headers": [{"name": "Subject", "value": "제목2"}], "body": {"data": _b64("본문2")}},
        },
    }
    messages_resource = _FakeMessagesResource(list_response, get_responses)
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    emails = adapter.fetch_new_emails()

    assert [e.message_id for e in emails] == ["msg-1", "msg-2"]
    assert emails[0].subject == "제목1"
    assert emails[1].body == "본문2"


def test_fetch_new_emails_returns_empty_list_when_inbox_has_no_unread_messages():
    messages_resource = _FakeMessagesResource({}, {})  # "messages" 키 자체가 없는 응답
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    assert adapter.fetch_new_emails() == []


def test_fetch_new_emails_skips_message_that_fails_to_parse_but_keeps_others():
    list_response = {"messages": [{"id": "broken"}, {"id": "ok"}]}
    get_responses = {
        "broken": {"internalDate": "not-a-number", "payload": {}},  # int() 변환 실패로 파싱 중 예외 유발
        "ok": {"id": "ok", "internalDate": "0", "payload": {"headers": [], "body": {"data": _b64("정상 본문")}}},
    }
    messages_resource = _FakeMessagesResource(list_response, get_responses)
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    emails = adapter.fetch_new_emails()

    assert [e.message_id for e in emails] == ["ok"]


def test_mark_processed_removes_unread_label():
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    adapter.mark_processed("msg-1")

    assert messages_resource.modify_calls == [("msg-1", {"removeLabelIds": ["UNREAD"]})]
