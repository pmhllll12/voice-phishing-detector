from application.services import ExplanationService, PatternDetectionService, RiskScoringService

detection_service = PatternDetectionService()
scoring_service = RiskScoringService()
explanation_service = ExplanationService()


def _explain(transcript: str):
    detection = detection_service.detect(transcript)
    risk = scoring_service.score(detection)
    return explanation_service.generate(detection, risk)


def test_benign_text_has_no_reasons():
    explanation = _explain("안녕하세요, 내일 회의 시간 확인차 연락드렸습니다.")

    assert explanation.reasons == []
    assert "저위험" in explanation.summary
    assert "0점" in explanation.summary
    assert explanation.narrative == explanation.summary


def test_high_risk_explanation_cites_every_detected_category():
    transcript = (
        "검찰청 수사관인데 귀하 계좌가 범죄에 연루되어 체포영장이 발부될 수 있습니다. "
        "지금 즉시 안전계좌로 이체하셔야 합니다."
    )
    explanation = _explain(transcript)

    assert "고위험" in explanation.summary
    assert "95점" in explanation.summary
    assert len(explanation.reasons) == 3
    assert any("기관사칭" in r for r in explanation.reasons)
    assert any("공포조성" in r for r in explanation.reasons)
    assert any("긴급송금유도" in r for r in explanation.reasons)
    # 매칭 키워드가 실제로 근거 문장에 인용되어야 한다 (N-04: 추적 가능한 근거)
    assert any("검찰청" in r for r in explanation.reasons)


def test_narrative_includes_summary_and_reasons():
    explanation = _explain("지금 즉시 안전계좌로 이체해주세요.")

    assert explanation.summary in explanation.narrative
    for reason in explanation.reasons:
        assert reason in explanation.narrative


def test_reason_mentions_category_weight():
    explanation = _explain("지금 즉시 안전계좌로 이체해주세요.")

    assert len(explanation.reasons) == 1
    assert "35점" in explanation.reasons[0]
