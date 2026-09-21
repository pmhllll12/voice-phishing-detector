# 우선순위 2(SMS/email 실채널 연동, 2026-09-02): Gmail 받은편지함을 실제로 폴링한다.
# domain/ports.py의 EmailSourcePort를 구현한다.
#
# WHY 폴링인가(웹훅이 아니라): Gmail의 실시간 푸시(Cloud Pub/Sub watch)는 외부에서
# 도달 가능한 공개 엔드포인트가 필요한데, 이 프로젝트는 아직 실배포 전이다(EC2를
# 시도했다가 Oracle Cloud로 전환 결정, docs/design.md 4장 참고) — 배포가 끝나기 전엔
# 웹훅을 받을 곳이 없다.
#
# 처리 상태 추적: 전용 라벨(_PROCESSED_LABEL_NAME)을 붙이는 방식으로 처리 완료를
# 표시한다 — 별도 상태 저장소 없이도 재시작에 안전하다(Gmail 자체가 상태를 들고
# 있음, 중복 처리 없음). 실배포 후 웹훅으로 전환할 때도 EmailSourcePort 인터페이스는
# 그대로 유지된다(N-06과 같은 원칙).
#
# ⚠️ WHY UNREAD 라벨을 건드리지 않는가(중요, 실제로 겪은 문제): 초기 버전은
# UNREAD 라벨을 제거하는 방식으로 처리 완료를 표시했다. 로컬 검증(2026-09-02) 중
# OAuth 동의 화면에서 새 테스트 계정이 아니라 브라우저에 이미 로그인돼 있던
# 실제 계정으로 잘못 연결되는 사고가 났는데, 그 상태로 폴링을 한 번 돌리자
# 실제 안 읽은 메일 약 100통이 전부 "읽음" 처리돼버렸다(다행히 메시지 ID를
# 전부 갖고 있어서 UNREAD 라벨을 다시 추가해 복구함). 그 사고 이후 "처리 완료
# 표시"가 사용자가 이미 갖고 있던 상태(안 읽음 여부)를 절대 바꾸지 않도록
# 전용 라벨 추가 방식(순수 추가 연산, 기존 라벨/읽음 상태에 부작용 없음)으로
# 다시 설계했다 — 어떤 계정이 실수로 연결되든 이 방식은 최소한 "메일을 읽은 것처럼
# 만들어버리는" 부작용은 낼 수 없다.
#
# ⚠️ 추가 안전장치: 검색 쿼리에 newer_than:1d를 기본으로 걸어서, 계정을 잘못
# 연결해도 첫 폴링이 메일함 전체 역사를 훑는 걸 막는다(블라스트 반경 최소화).
#
# 인증: 이 어댑터는 이미 만들어진 Gmail API `service` 객체를 주입받는다(테스트에서
# 가짜 service로 대체 가능하게) — OAuth 로그인/토큰 갱신은 build_gmail_service()가
# 담당하고, 실제 폴링 스크립트(scripts/poll_gmail_inbox.py)에서만 쓴다. 최초 1회
# 동의는 scripts/gmail_oauth_setup.py로 받는다(README "Gmail 이메일 채널 연동" 절 참고,
# 계정 선택 시 반드시 테스트용 계정인지 재확인하라는 경고 포함).

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any

from domain.entities import EmailMessage

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
_PROCESSED_LABEL_NAME = "VPS-Detector-Processed"


def _decode_base64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _find_body(payload: dict[str, Any]) -> str:
    """멀티파트든 아니든 text/plain을 우선하고 없으면 text/html을 최소한만 정제해
    쓴다 — 완전한 HTML 파서는 아니고(외부 의존성 추가 없이 태그만 대충 벗겨낸다),
    F-01/F-02 판정은 태그가 약간 섞여도 키워드/LLM 판단에 큰 영향이 없다는 판단."""
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data")

    if body_data and mime_type in ("text/plain", ""):
        return _decode_base64url(body_data)

    html_fallback = None
    for part in payload.get("parts", []) or []:
        part_mime = part.get("mimeType", "")
        if part_mime == "text/plain" and part.get("body", {}).get("data"):
            return _decode_base64url(part["body"]["data"])
        if part_mime == "text/html" and part.get("body", {}).get("data") and html_fallback is None:
            html_fallback = _decode_base64url(part["body"]["data"])
        if part.get("parts"):  # multipart/alternative가 중첩된 경우
            nested = _find_body(part)
            if nested:
                return nested

    if html_fallback is not None:
        return re.sub(r"<[^>]+>", " ", html_fallback)

    if body_data:
        return _decode_base64url(body_data)

    return ""


def _parse_message(raw: dict[str, Any]) -> tuple[str, str, str, datetime]:
    """Gmail API messages.get(format='full') 응답 하나를 (message_id, subject, body,
    received_at) 튜플로 파싱한다. 순수 함수라 네트워크 없이 단위 테스트 가능하다."""
    headers = raw.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers if h.get("name", "").lower() == "subject"), "(제목 없음)")
    body = _find_body(raw.get("payload", {}))
    internal_date_ms = int(raw.get("internalDate", "0"))
    received_at = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
    return raw["id"], subject, body, received_at


class GmailEmailSourceAdapter:
    def __init__(self, service: Any, lookback_query: str = "newer_than:1d"):
        self._service = service
        self._lookback_query = lookback_query
        self._processed_label_id: str | None = None

    def _get_or_create_processed_label_id(self) -> str:
        if self._processed_label_id is not None:
            return self._processed_label_id

        labels = self._service.users().labels().list(userId="me").execute().get("labels", [])
        existing = next((l for l in labels if l["name"] == _PROCESSED_LABEL_NAME), None)
        if existing is not None:
            self._processed_label_id = existing["id"]
            return self._processed_label_id

        created = (
            self._service.users()
            .labels()
            .create(userId="me", body={"name": _PROCESSED_LABEL_NAME, "labelListVisibility": "labelHide"})
            .execute()
        )
        self._processed_label_id = created["id"]
        return self._processed_label_id

    def fetch_new_emails(self) -> list[EmailMessage]:
        try:
            self._get_or_create_processed_label_id()  # 라벨이 없으면 먼저 만들어둔다(검색은 이름으로 함)
            query = f"-label:{_PROCESSED_LABEL_NAME} {self._lookback_query}".strip()
            listing = (
                self._service.users()
                .messages()
                .list(userId="me", q=query, labelIds=["INBOX"])
                .execute()
            )
        except Exception as e:  # noqa: BLE001 — Gmail API 클라이언트 예외 타입이 다양해 광범위하게 잡는다
            logger.warning("Gmail 받은편지함 조회 실패 — 이번 폴링은 건너뜀: %s", e)
            return []

        emails = []
        for item in listing.get("messages", []):
            try:
                raw = self._service.users().messages().get(userId="me", id=item["id"], format="full").execute()
                message_id, subject, body, received_at = _parse_message(raw)
            except Exception as e:  # noqa: BLE001
                logger.warning("메일(%s) 파싱 실패 — 건너뜀: %s", item.get("id"), e)
                continue
            emails.append(EmailMessage(message_id=message_id, subject=subject, body=body, received_at=received_at))
        return emails

    def mark_processed(self, message_id: str) -> None:
        """전용 라벨을 "추가"만 한다 — 기존 라벨/읽음 상태는 절대 건드리지 않는다
        (파일 상단 "WHY UNREAD 라벨을 건드리지 않는가" 참고)."""
        label_id = self._get_or_create_processed_label_id()
        self._service.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": [label_id]}
        ).execute()


def build_gmail_service(token_path: str):
    """scripts/poll_gmail_inbox.py 전용 팩토리 — OAuth 토큰을 읽어(만료됐으면 자동
    갱신) 실제 Gmail API service 객체를 만든다. 어댑터 단위 테스트는 이 함수를 안 쓰고
    가짜 service를 직접 주입한다(google-auth-oauthlib 등은 테스트 의존성에 없음)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(token_path, _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)
