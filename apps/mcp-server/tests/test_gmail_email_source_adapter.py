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
        self.list_calls: list[str] = []
        self.modify_calls: list[tuple[str, dict]] = []

    def list(self, userId, q, labelIds):
        self.list_calls.append(q)
        return _FakeRequest(self._list_response)

    def get(self, userId, id, format):
        return _FakeRequest(self._get_responses[id])

    def modify(self, userId, id, body):
        self.modify_calls.append((id, body))
        return _FakeRequest({})


class _FakeLabelsResource:
    """기존 라벨이 없는 상태에서 시작 — create()가 한 번 호출되고 이후엔
    캐시된 id를 재사용하는지(list를 반복 호출하지 않는지)까지 확인한다."""

    def __init__(self, existing_labels: list[dict] | None = None):
        self.existing_labels = existing_labels or []
        self.list_call_count = 0
        self.created: list[dict] = []

    def list(self, userId):
        self.list_call_count += 1
        return _FakeRequest({"labels": self.existing_labels})

    def create(self, userId, body):
        self.created.append(body)
        return _FakeRequest({"id": "Label_new123", "name": body["name"]})


class _FakeUsers:
    def __init__(self, messages_resource, labels_resource):
        self._messages_resource = messages_resource
        self._labels_resource = labels_resource

    def messages(self):
        return self._messages_resource

    def labels(self):
        return self._labels_resource


class _FakeGmailService:
    def __init__(self, messages_resource, labels_resource=None):
        self._messages_resource = messages_resource
        self._labels_resource = labels_resource or _FakeLabelsResource()

    def users(self):
        return _FakeUsers(self._messages_resource, self._labels_resource)


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


# --- GmailEmailSourceAdapter: 목록 조회 -> 개별 조회 -> 처리 완료 표시(전용 라벨) ---


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


def test_fetch_new_emails_query_excludes_processed_label_and_bounds_lookback():
    """회귀 가드(2026-09-02 실측 사고 이후 추가): is:unread를 더 이상 쓰지 않고,
    전용 라벨로 제외 + newer_than 기본 상한을 건다 — 계정이 잘못 연결돼도 블라스트
    반경이 제한된다(gmail_email_source_adapter.py 상단 주석 참고)."""
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    adapter.fetch_new_emails()

    assert messages_resource.list_calls == ["-label:VPS-Detector-Processed newer_than:1d"]


def test_fetch_new_emails_returns_empty_list_when_inbox_has_no_new_messages():
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


def test_mark_processed_adds_dedicated_label_without_touching_unread():
    """회귀 가드(2026-09-02 실측 사고): removeLabelIds로 UNREAD를 지우면 실제 안
    읽은 메일이 읽음 처리되는 부작용이 있었다 — addLabelIds로 전용 라벨만 "추가"
    해야 한다."""
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource))

    adapter.mark_processed("msg-1")

    assert messages_resource.modify_calls == [("msg-1", {"addLabelIds": ["Label_new123"]})]
    assert "removeLabelIds" not in str(messages_resource.modify_calls)


def test_mark_processed_creates_label_once_when_missing():
    labels_resource = _FakeLabelsResource(existing_labels=[])
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource, labels_resource))

    adapter.mark_processed("msg-1")
    adapter.mark_processed("msg-2")

    assert len(labels_resource.created) == 1  # 두 번째 호출은 캐시된 id를 재사용
    assert labels_resource.created[0]["name"] == "VPS-Detector-Processed"


def test_mark_processed_reuses_existing_label_without_creating_duplicate():
    labels_resource = _FakeLabelsResource(existing_labels=[{"id": "Label_existing", "name": "VPS-Detector-Processed"}])
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource, labels_resource))

    adapter.mark_processed("msg-1")

    assert labels_resource.created == []
    assert messages_resource.modify_calls == [("msg-1", {"addLabelIds": ["Label_existing"]})]


def test_lookback_query_is_configurable():
    messages_resource = _FakeMessagesResource({}, {})
    adapter = GmailEmailSourceAdapter(_FakeGmailService(messages_resource), lookback_query="newer_than:7d")

    adapter.fetch_new_emails()

    assert messages_resource.list_calls == ["-label:VPS-Detector-Processed newer_than:7d"]
