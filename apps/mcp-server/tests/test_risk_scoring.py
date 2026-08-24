from application.services import PatternDetectionService, RiskScoringService
from domain.entities import RiskLevel

detection_service = PatternDetectionService()
scoring_service = RiskScoringService()


def _score(transcript: str):
    detection = detection_service.detect(transcript)
    return scoring_service.score(detection)


def test_benign_text_scores_zero_and_low():
    risk = _score("안녕하세요, 내일 회의 시간 확인차 연락드렸습니다.")
    assert risk.score == 0
    assert risk.level == RiskLevel.LOW


def test_single_category_is_low_risk():
    risk = _score("지금 즉시 안전계좌로 이체해주세요.")  # urgent_transfer(35점)만 매칭
    assert risk.score == 35
    assert risk.level == RiskLevel.LOW


def test_two_categories_is_medium_risk():
    # authority_impersonation(30) + fear_inducement(30) = 60점
    risk = _score("검찰청 수사관인데, 귀하 계좌가 범죄에 연루되었습니다.")
    assert risk.score == 60
    assert risk.level == RiskLevel.MEDIUM


def test_three_core_categories_is_high_risk():
    # authority_impersonation(30) + fear_inducement(30) + urgent_transfer(35) = 95점, capped 100 내
    transcript = (
        "검찰청 수사관인데 귀하 계좌가 범죄에 연루되어 체포영장이 발부될 수 있습니다. "
        "지금 즉시 안전계좌로 이체하셔야 합니다."
    )
    risk = _score(transcript)
    assert risk.score == 95
    assert risk.level == RiskLevel.HIGH


def test_score_is_capped_at_100():
    transcript = (
        "검찰청 수사관인데 귀하 계좌가 범죄에 연루되어 체포영장이 발부될 수 있습니다. "
        "지금 즉시 안전계좌로 이체하시고, 주민등록번호와 계좌번호와 비밀번호도 알려주세요."
    )
    risk = _score(transcript)
    assert risk.score == 100
    assert risk.level == RiskLevel.HIGH


def test_breakdown_lists_contributing_categories():
    risk = _score("지금 즉시 안전계좌로 이체해주세요.")
    assert len(risk.breakdown) == 1
    assert risk.breakdown[0].weight == 35
