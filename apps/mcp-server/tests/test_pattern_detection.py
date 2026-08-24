from application.services import PatternDetectionService
from domain.entities import PatternCategory

service = PatternDetectionService()


def test_detects_authority_impersonation_and_urgent_transfer():
    transcript = "검찰청 수사관인데 지금 즉시 안전계좌로 이체하셔야 합니다."
    result = service.detect(transcript)

    categories = {p.category for p in result.detected_patterns}
    assert PatternCategory.AUTHORITY_IMPERSONATION in categories
    assert PatternCategory.URGENT_TRANSFER in categories
    assert result.has_risk_indicators


def test_no_match_on_benign_text():
    transcript = "안녕하세요, 내일 회의 시간 확인차 연락드렸습니다."
    result = service.detect(transcript)

    assert result.detected_patterns == []
    assert not result.has_risk_indicators


def test_matched_keywords_are_recorded():
    transcript = "귀하의 계좌가 범죄에 이용되어 체포영장이 발부될 수 있습니다."
    result = service.detect(transcript)

    fear = next(p for p in result.detected_patterns if p.category == PatternCategory.FEAR_INDUCEMENT)
    assert "체포영장" in fear.matched_keywords
    assert "계좌가 범죄에 이용" in fear.matched_keywords
