# 역방향 신원확인 POC: 확인 불가 시 보호자 알림의 mock 구현. domain/ports.py의
# GuardianNotificationPort를 구현한다.
#
# mcp-server F-07 submit_report mock과 같은 방식 — 실제 문자/푸시/전화는 발송하지 않고,
# "알림이 발송됐어야 한다"는 사실과 notification_id만 기록한다(프로세스 메모리, 재시작 시
# 사라짐). 보호자 연락처 등록 기능도 없다.

import logging
import uuid
from datetime import datetime, timezone

from src.domain.identity_verification import GuardianNotification

logger = logging.getLogger(__name__)

MOCK_NOTE = "MOCK: 실제 보호자 알림(문자/푸시) 발송 없음 — 모의 시연용 기록만 남김"


class MockGuardianNotifier:
    def __init__(self):
        self.sent: list[GuardianNotification] = []

    def notify(self, call_id: str, reason: str) -> GuardianNotification:
        notification = GuardianNotification(
            notification_id=str(uuid.uuid4()),
            call_id=call_id,
            status="logged",
            created_at=datetime.now(timezone.utc),
            note=MOCK_NOTE,
        )
        self.sent.append(notification)
        logger.info("보호자 알림(mock) 기록: call_id=%s reason=%s", call_id, reason)
        return notification
