# 역방향 신원확인 POC: 통화별 신원확인 결과의 인메모리 저장소. domain/ports.py의
# CallVerificationLogPort를 구현한다.
#
# WHY postgres가 아닌가: 판정 결과 감사증적(call_analysis_results)은 append-only 트리거로
# UPDATE가 막혀 있어 기존 행에 결과를 덧붙일 수 없고, 별도 테이블을 만들면 스키마 변경이
# POC 범위를 넘는다. 재시작 시 사라지는 것은 POC의 한계로 둔다(docs/poc-mobile-id.md 참고).

import threading
from collections import defaultdict

from src.domain.identity_verification import CallVerificationRecord


class InMemoryCallVerificationLog:
    def __init__(self):
        self._records: dict[str, list[CallVerificationRecord]] = defaultdict(list)
        self._lock = threading.Lock()

    def add(self, record: CallVerificationRecord) -> None:
        with self._lock:
            self._records[record.call_id].append(record)

    def list_for_call(self, call_id: str) -> list[CallVerificationRecord]:
        with self._lock:
            return list(self._records.get(call_id, []))
