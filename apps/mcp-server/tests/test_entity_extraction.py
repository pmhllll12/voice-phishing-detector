# domain/entity_extraction.py 단위 테스트. apps/api의 test_pii_masking.py와 같은 목적
# (정규식 커버리지 확인)이지만, 지우는 게 아니라 값을 뽑아 정규화하는지 확인한다.

from domain.entities import EntityType, ExtractedEntity
from domain.entity_extraction import extract_entities


def test_extracts_and_normalizes_phone_number_regardless_of_formatting():
    result = extract_entities("문의사항 있으시면 010-1234-5678로 연락주세요")

    assert ExtractedEntity(EntityType.PHONE, "01012345678") in result


def test_same_phone_number_normalizes_identically_with_and_without_hyphens():
    with_hyphens = extract_entities("010-1234-5678로 다시 전화드리겠습니다")
    without_hyphens = extract_entities("01012345678로 다시 전화드리겠습니다")

    assert with_hyphens == without_hyphens


def test_extracts_account_number_after_removing_phone_and_url():
    result = extract_entities("국민은행 123456-78-901234 계좌로 입금 부탁드립니다")

    assert any(e.entity_type == EntityType.ACCOUNT and e.value == "12345678901234" for e in result)


def test_phone_digits_are_not_double_counted_as_account_number():
    result = extract_entities("010-1234-5678로 연락주세요")

    assert not any(e.entity_type == EntityType.ACCOUNT for e in result)


def test_extracts_and_normalizes_url_to_host():
    result = extract_entities("이 링크를 확인하세요 https://Evil-Bank.example.com/login?id=1")

    assert ExtractedEntity(EntityType.URL, "evil-bank.example.com") in result


def test_returns_empty_list_for_text_without_entities():
    assert extract_entities("내일 회의 시간 확인차 연락드렸습니다.") == []


def test_deduplicates_repeated_entities_preserving_first_occurrence():
    result = extract_entities("010-1234-5678로 연락주세요. 다시 한번, 010-1234-5678입니다.")

    assert result.count(ExtractedEntity(EntityType.PHONE, "01012345678")) == 1
