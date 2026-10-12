# N-03 개인정보 마스킹 검증. domain/pii_masking.py는 정규식 기반 v1이라 정확도가
# 검증된 NER이 아니다(파일 상단 주석의 한계 참고) — 이 테스트는 "의도한 패턴이 실제로
# 지워지는가"를 확인하는 것이지, 실제 통화 텍스트에서의 재현율/정밀도를 보증하지 않는다.

from src.domain.pii_masking import mask_pii


def test_masks_mobile_phone_number_with_dashes():
    assert mask_pii("010-1234-5678로 다시 전화드릴게요") == "[전화번호]로 다시 전화드릴게요"


def test_masks_mobile_phone_number_without_dashes():
    assert mask_pii("01012345678로 연락주세요") == "[전화번호]로 연락주세요"


def test_masks_landline_number():
    assert mask_pii("02-1234-5678로 확인 전화가 갈 겁니다") == "[전화번호]로 확인 전화가 갈 겁니다"


def test_masks_resident_registration_number():
    assert mask_pii("주민등록번호 901231-1234567 불러주세요") == "주민등록번호 [주민등록번호] 불러주세요"


def test_masks_long_digit_sequence_as_account_number():
    assert mask_pii("계좌번호 123456789012로 입금하세요") == "계좌번호 [계좌번호]로 입금하세요"


def test_masks_account_number_with_dashes():
    assert mask_pii("농협 301-1234-5678-01 계좌로 보내세요") == "농협 [계좌번호] 계좌로 보내세요"


def test_masks_name_with_honorific():
    assert mask_pii("김민수님 본인 확인 부탁드립니다") == "[이름] 본인 확인 부탁드립니다"
    assert mask_pii("박서준 씨 되시죠?") == "[이름] 되시죠?"


def test_does_not_mask_short_numbers_or_plain_pattern_phrases():
    """계좌번호/전화번호 요구 '문구'는 F-01/F-02 판정 근거라 지우면 안 된다 — PII masking은
    실제 숫자/이름 값만 지운다."""
    text = "계좌번호와 비밀번호를 알려주세요, 지금 즉시 안전계좌로 이체하세요"
    assert mask_pii(text) == text


def test_masks_multiple_pii_types_in_one_transcript():
    text = "검찰청 수사관인데 010-1234-5678로 전화드렸습니다. 김민수님 계좌 123456789012로 이체하세요."
    masked = mask_pii(text)
    assert "[전화번호]" in masked
    assert "[이름]" in masked
    assert "[계좌번호]" in masked
    assert "010-1234-5678" not in masked
    assert "123456789012" not in masked
    assert "검찰청 수사관" in masked  # 판정 근거 문구는 보존
