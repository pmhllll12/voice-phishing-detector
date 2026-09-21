# 우선순위 2(크로스채널 상관관계 탐지): 통화/문자/이메일 텍스트에서 전화번호/계좌번호/URL을
# 정규식으로 추출한다. apps/api/src/domain/pii_masking.py와 같은 문제(정확한 값을 결정론적
# 으로 찾아야 함)라 규칙 기반이 더 적합하다는 판단도 동일 — 다만 목적이 "지우기"가 아니라
# "값을 뽑아서 다른 채널과 대조하기"라 마스킹 태그가 아니라 정규화된 원본 값을 반환한다.
#
# apps/api에도 똑같은 정규식이 있다(pii_masking.py) — 공유 모듈로 뽑지 않고 복붙한 이유는
# rest_server.py 상단 주석과 같다("공유 모듈로 뽑을 만큼 커지면 그때 리팩터링"). 다만 목적이
# 서로 달라(지우기 vs 추출) 완전히 같은 코드는 아니다.
#
# ⚠️ 한계: pii_masking.py와 동일하게 계좌번호는 은행마다 자릿수/구분 형식이 달라
# "10~16자리 숫자(구분기호 허용)"라는 느슨한 휴리스틱을 쓴다 — 계좌번호가 아닌 다른 긴
# 숫자(사건번호 등)를 오탐할 수 있다. 정량 평가는 아직 안 했다(N-03 PII 마스킹처럼
# 실측 데이터셋으로 정밀도/재현율을 재보정하는 건 다음 이터레이션 후보).

import re
from urllib.parse import urlparse

from .entities import EntityType, ExtractedEntity

_URL = re.compile(r"https?://[^\s]+|www\.[^\s]+")

_PHONE_NUMBER = re.compile(
    r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}"  # 휴대폰: 010-1234-5678 등
    r"|0(?:2|[3-6]\d)[-\s]?\d{3,4}[-\s]?\d{4}"  # 유선: 02-123-4567, 031-123-4567 등
)

# URL/전화번호를 먼저 지운 "나머지" 텍스트에서만 적용 — pii_masking.py의 _ACCOUNT_NUMBER와
# 동일한 휴리스틱(10~16자리 숫자, 구분기호 허용).
_ACCOUNT_NUMBER = re.compile(r"\d[\d\-\s]{8,20}\d")

_TRAILING_PUNCTUATION = re.compile(r"[.,)\]}·、。]+$")


def _blank_out(pattern: re.Pattern[str], text: str) -> tuple[list[str], str]:
    """pattern에 매칭된 부분을 원래 길이만큼 공백으로 지우면서(문자 오프셋 유지) 매칭된
    원본 문자열 리스트를 함께 돌려준다 — 뒤 패턴이 이미 소비된 구간을 다시 매칭하지
    않도록(예: 전화번호 자릿수를 계좌번호 정규식이 다시 잡는 것) pii_masking.py의
    순차 치환 방식을 추출용으로 응용했다."""
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
    "010-1234-5678"과 "01012345678"처럼 채널마다 표기가 달라도 같은 값이면 동일
    엔티티로 취급되도록 정규화한다(전화번호/계좌번호는 숫자만, URL은 host만)."""
    urls, working = _blank_out(_URL, text)
    phones, working = _blank_out(_PHONE_NUMBER, working)
    accounts, _ = _blank_out(_ACCOUNT_NUMBER, working)

    entities = (
        [ExtractedEntity(EntityType.URL, _normalize_url(v)) for v in urls]
        + [ExtractedEntity(EntityType.PHONE, _normalize_digits(v)) for v in phones]
        + [ExtractedEntity(EntityType.ACCOUNT, _normalize_digits(v)) for v in accounts]
    )

    seen: set[tuple[EntityType, str]] = set()
    deduped: list[ExtractedEntity] = []
    for entity in entities:
        key = (entity.entity_type, entity.value)
        if key not in seen and entity.value:
            seen.add(key)
            deduped.append(entity)
    return deduped
