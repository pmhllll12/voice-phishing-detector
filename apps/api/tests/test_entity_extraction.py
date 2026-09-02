# domain/entity_extraction.py 단위 테스트. apps/mcp-server의 동명 테스트와 목적이
# 같다 — 두 앱이 정규식을 복붙해 각자 갖고 있어서(entity_extraction.py 상단 주석
# 참고) 각자 검증한다.

from src.domain.entities import ExtractedEntity
from src.domain.entity_extraction import extract_entities


def test_extracts_and_normalizes_phone_number_regardless_of_formatting():
    result = extract_entities("문의사항 있으시면 010-1234-5678로 연락주세요")

    assert ExtractedEntity("phone", "01012345678") in result


def test_extracts_account_number_after_removing_phone_and_url():
    result = extract_entities("국민은행 123456-78-901234 계좌로 입금 부탁드립니다")

    assert any(e.entity_type == "account" and e.value == "12345678901234" for e in result)


def test_extracts_and_normalizes_url_to_host():
    result = extract_entities("이 링크를 확인하세요 https://Evil-Bank.example.com/login?id=1")

    assert ExtractedEntity("url", "evil-bank.example.com") in result


def test_returns_empty_list_for_text_without_entities():
    assert extract_entities("내일 회의 시간 확인차 연락드렸습니다.") == []


def test_masked_transcript_yields_no_entities():
    """N-03과의 상호작용 회귀 가드: pii_masking.py가 이미 지운 텍스트에서는 당연히
    아무것도 추출되면 안 된다 — AnalyzeCallService가 반드시 raw_transcript(마스킹 전)
    에서 추출해야 하는 이유(entity_extraction.py 상단 주석 참고)."""
    masked = "[전화번호]로 다시 연락드리겠습니다. [계좌번호]로 입금하세요."

    assert extract_entities(masked) == []
