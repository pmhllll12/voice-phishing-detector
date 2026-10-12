# 우선순위 2가 CallAnalysisService.execute()에 올바르게 결합되는지 검증한다.
# test_call_analysis_similar_cases.py와 같은 패턴 — 가짜 포트로 실제 rag-worker/DB 없이
# 판정 파이프라인만 확인한다. 실제 상관관계 매칭 로직 자체는
# test_multichannel_correlation_service.py에서 이미 검증했다.

import datetime

from application.services import CallAnalysisService
from domain.entities import (
    CallAnalysisResult,
    Channel,
    CorrelationMatch,
    CorrelationResult,
    DetectedPattern,
    EntityType,
    PatternCategory,
    PatternDetectionResult,
    RiskAssessment,
    RiskExplanation,
    RiskLevel,
)


def _medium_risk_result() -> CallAnalysisResult:
    detection = PatternDetectionResult(
        transcript="010-1234-5678로 안전계좌 이체 부탁드립니다",
        detected_patterns=[DetectedPattern(category=PatternCategory.URGENT_TRANSFER, matched_keywords=["안전계좌로 옮기"])],
    )
    risk = RiskAssessment(score=35, level=RiskLevel.LOW, breakdown=[])
    explanation = RiskExplanation(
        summary="저위험 등급 (위험도 35점) — 경미한 의심 정황이 확인되었으나 현재 위험도는 낮습니다.",
        reasons=["[긴급송금유도] ..."],
        narrative="저위험 등급 (위험도 35점) — 경미한 의심 정황이 확인되었으나 현재 위험도는 낮습니다.\n\n근거:\n- [긴급송금유도] ...",
    )
    return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)


def _benign_result_no_entities() -> CallAnalysisResult:
    detection = PatternDetectionResult(transcript="내일 회의 시간 확인차 연락드렸습니다.", detected_patterns=[])
    risk = RiskAssessment(score=0, level=RiskLevel.LOW, breakdown=[])
    explanation = RiskExplanation(summary="저위험 등급 (위험도 0점) — ...", reasons=[], narrative="저위험 등급 (위험도 0점) — ...")
    return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)


class _FakeCallAnalysisPort:
    def __init__(self, result: CallAnalysisResult):
        self._result = result

    def analyze(self, transcript: str) -> CallAnalysisResult:
        return self._result


class _FakeCorrelationService:
    def __init__(self, result: CorrelationResult):
        self._result = result
        self.received: tuple | None = None

    def correlate(self, channel, entities, occurred_at, context_excerpt, current_risk_score=None):
        self.received = (channel, entities, current_risk_score)
        return self._result


_MATCH = CorrelationMatch(
    entity_type=EntityType.PHONE,
    entity_value="*******5678",
    matched_channel=Channel.SMS,
    matched_at=datetime.datetime(2026, 9, 2, 11, 48, tzinfo=datetime.timezone.utc),
    context_excerpt="문자 발췌",
)


def test_correlation_boost_raises_score_and_appends_reason():
    correlation = CorrelationResult(
        matches=[_MATCH],
        risk_boost=15,
        reasons=["12분 전 문자 채널에서 동일 전화번호(*******5678)이(가) 감지되었습니다 — 크로스채널 상관관계"],
        updated_risk_score=50,
        updated_risk_level=RiskLevel.MEDIUM,
    )
    correlation_port = _FakeCorrelationService(correlation)
    service = CallAnalysisService(_FakeCallAnalysisPort(_medium_risk_result()), correlation_service=correlation_port)

    result = service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다")

    assert result.risk.score == 50
    assert result.risk.level == RiskLevel.MEDIUM
    assert result.risk.correlation_boost == 15
    assert any("크로스채널 상관관계" in r for r in result.explanation.reasons)
    assert "크로스채널 상관관계" in result.explanation.narrative
    # 원래 F-01/F-02 근거는 그대로 유지되어야 한다
    assert "[긴급송금유도] ..." in result.explanation.reasons
    # 전화번호를 넘겼는지 확인 (current_risk_score도 함께 전달됐는지)
    assert correlation_port.received[2] == 35


def test_no_matches_leaves_result_unchanged():
    correlation_port = _FakeCorrelationService(CorrelationResult(updated_risk_score=35, updated_risk_level=RiskLevel.LOW))
    base_result = _medium_risk_result()
    service = CallAnalysisService(_FakeCallAnalysisPort(base_result), correlation_service=correlation_port)

    result = service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다")

    assert result is base_result


def test_transcript_without_entities_skips_correlation_lookup():
    correlation_port = _FakeCorrelationService(CorrelationResult())
    base_result = _benign_result_no_entities()
    service = CallAnalysisService(_FakeCallAnalysisPort(base_result), correlation_service=correlation_port)

    result = service.execute("내일 회의 시간 확인차 연락드렸습니다.")

    assert result is base_result
    assert correlation_port.received is None


def test_analysis_is_unaffected_without_correlation_service():
    base_result = _medium_risk_result()
    service = CallAnalysisService(_FakeCallAnalysisPort(base_result))

    result = service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다")

    assert result is base_result


def test_flagged_url_alone_raises_score_even_without_cross_channel_match():
    """회귀 가드: matches가 비어 있어도 flagged_urls(Google Safe Browsing)만으로
    가산점이 붙으면 결과에 반영돼야 한다 — `if correlation.matches:`만 보면 이 경우를
    놓친다(2026-09-02 SMS/email 실채널 연동 작업 중 발견/수정)."""
    correlation = CorrelationResult(
        matches=[],
        flagged_urls=["evil.example.com"],
        risk_boost=40,
        reasons=["URL(evil.example.com)이 Google Safe Browsing에 등록된 악성 사이트로 확인되었습니다 — 외부 위협 인텔리전스 연동"],
        updated_risk_score=75,
        updated_risk_level=RiskLevel.HIGH,
    )
    correlation_port = _FakeCorrelationService(correlation)
    service = CallAnalysisService(_FakeCallAnalysisPort(_medium_risk_result()), correlation_service=correlation_port)

    result = service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다")

    assert result.risk.score == 75
    assert result.risk.level == RiskLevel.HIGH
    assert any("Google Safe Browsing" in r for r in result.explanation.reasons)


def test_channel_and_occurred_at_are_forwarded_to_correlation_service():
    """우선순위 2(SMS/email 실채널 연동): channel/occurred_at을 명시하면 그대로
    전달돼야 한다 — EmailIngestionService가 channel=EMAIL로 이 메서드를 재사용한다."""
    occurred_at = datetime.datetime(2026, 9, 2, 9, 0, tzinfo=datetime.timezone.utc)
    correlation_port = _FakeCorrelationService(CorrelationResult())
    service = CallAnalysisService(
        _FakeCallAnalysisPort(_medium_risk_result()), correlation_service=correlation_port
    )

    service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다", channel=Channel.EMAIL, occurred_at=occurred_at)

    assert correlation_port.received[0] == Channel.EMAIL


def test_channel_defaults_to_call_for_existing_callers():
    correlation_port = _FakeCorrelationService(CorrelationResult())
    service = CallAnalysisService(
        _FakeCallAnalysisPort(_medium_risk_result()), correlation_service=correlation_port
    )

    service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다")

    assert correlation_port.received[0] == Channel.CALL
