# 우선순위 2(크로스채널 상관관계 탐지)의 apps/api 측 절반: mask_pii()가 지우기 "전"의
# raw_transcript에서 전화번호/계좌번호/URL을 추출한다. apps/mcp-server/src/domain/
# entity_extraction.py와 정규식이 사실상 동일하다 — 공유 모듈로 뽑지 않고 복붙한 이유는
# pii_masking.py/rest_server.py 상단 주석과 같다("공유 모듈로 뽑을 만큼 커지면 그때
# 리팩터링"). 두 앱이 서로 다른 프로세스/배포 단위라는 점도 동일하게 적용된다.
#
# WHY 이게 mcp-server가 아니라 여기(apps/api)에 있는가: mcp-server에 보내는
# transcript는 mask_pii()가 이미 적용된 뒤라 전화번호/계좌번호가 "[전화번호]"/
# "[계좌번호]" 태그로 치환돼 있다(pii_masking.py 참고) — 그 텍스트에서는 추출할 값이
# 없다. 크로스채널 상관관계는 실제 식별값을 알아야 매칭이 성립하므로, 원문(raw_transcript)
# 을 아직 들고 있는 이 계층에서 먼저 추출한 뒤 "값만"(원문 전체가 아니라) mcp-server로
# 넘긴다(application/services.py의 AnalyzeCallService, docs/design.md 7장 참고).

import re
from urllib.parse import urlparse

from .entities import ExtractedEntity

_URL = re.compile(r"https?://[^\s]+|www\.[^\s]+")

_PHONE_NUMBER = re.compile(
    r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}"
    r"|0(?:2|[3-6]\d)[-\s]?\d{3,4}[-\s]?\d{4}"
)

_ACCOUNT_NUMBER = re.compile(r"\d[\d\-\s]{8,20}\d")

_TRAILING_PUNCTUATION = re.compile(r"[.,)\]}·、。]+$")


def _blank_out(pattern: re.Pattern[str], text: str) -> tuple[list[str], str]:
    found: list[str] = []

    def _record(match: re.Match[str]) -> str:
        found.append(match.group(0))
        return " " * len(match.group(0))

    return found, pattern.sub(_record, text)


def _normalize_digits(raw: str) -> str:
    return re.sub(r"[^\d]", "", raw)


def _normalize_url(raw: str) -> str:
    cleaned = _TRAILING_PUNCTUATION.sub("", raw)
    candidate = cleaned if "://" in cleaned else f"http://{cleaned}"
    netloc = urlparse(candidate).netloc.lower()
    return netloc or cleaned.lower()


def extract_entities(text: str) -> list[ExtractedEntity]:
    """전화번호/계좌번호/URL을 정규화된 값으로 추출한다(중복 제거, 최초 등장 순서 유지).
    apps/mcp-server/src/domain/entity_extraction.py의 동명 함수와 동작이 동일하다 —
    상세 주석은 그쪽 참고."""
    urls, working = _blank_out(_URL, text)
    phones, working = _blank_out(_PHONE_NUMBER, working)
    accounts, _ = _blank_out(_ACCOUNT_NUMBER, working)

    entities = (
        [ExtractedEntity("url", _normalize_url(v)) for v in urls]
        + [ExtractedEntity("phone", _normalize_digits(v)) for v in phones]
        + [ExtractedEntity("account", _normalize_digits(v)) for v in accounts]
    )

    seen: set[tuple[str, str]] = set()
    deduped: list[ExtractedEntity] = []
    for entity in entities:
        key = (entity.entity_type, entity.value)
        if key not in seen and entity.value:
            seen.add(key)
            deduped.append(entity)
    return deduped
