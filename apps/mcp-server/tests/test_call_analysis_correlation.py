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
