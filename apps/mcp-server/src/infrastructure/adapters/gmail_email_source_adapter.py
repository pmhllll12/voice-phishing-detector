# 우선순위 2(SMS/email 실채널 연동, 2026-09-02): Gmail 받은편지함을 실제로 폴링한다.
# domain/ports.py의 EmailSourcePort를 구현한다.
#
# WHY 폴링인가(웹훅이 아니라): Gmail의 실시간 푸시(Cloud Pub/Sub watch)는 외부에서
# 도달 가능한 공개 엔드포인트가 필요한데, 이 프로젝트는 아직 실배포 전이다(EC2를
# 시도했다가 Oracle Cloud로 전환 결정, docs/design.md 4장 참고) — 배포가 끝나기 전엔
# 웹훅을 받을 곳이 없다. "is:unread" 검색으로 폴링하고 처리 후 UNREAD 라벨을 지우는
# 방식은 Gmail 자체가 처리 상태를 들고 있어서 이 프로세스가 별도 상태 저장소 없이도
# 재시작에 안전하다(중복 처리 없음) — 실배포 후 웹훅으로 전환할 때도 EmailSourcePort
# 인터페이스는 그대로 유지된다(N-06과 같은 원칙).
#
# 인증: 이 어댑터는 이미 만들어진 Gmail API `service` 객체를 주입받는다(테스트에서
# 가짜 service로 대체 가능하게) — OAuth 로그인/토큰 갱신은 build_gmail_service()가
# 담당하고, 실제 폴링 스크립트(scripts/poll_gmail_inbox.py)에서만 쓴다. 최초 1회
# 동의는 scripts/gmail_oauth_setup.py로 받는다(README "Gmail 이메일 채널 연동" 절 참고).

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone
from typing import Any

from domain.entities import EmailMessage

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


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
    def __init__(self, service: Any):
        self._service = service

    def fetch_new_emails(self) -> list[EmailMessage]:
        try:
            listing = self._service.users().messages().list(userId="me", q="is:unread", labelIds=["INBOX"]).execute()
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
        self._service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
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
