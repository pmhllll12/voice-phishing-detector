# F-04(유사사례) 검색 결과가 F-05(판정근거)에 결합되는지 검증한다. CallAnalysisService가
# rag-worker 없이도 독립적으로 동작해야 한다는 기존 설계 원칙(ExplanationService 상단
# 주석 참고)이 깨지지 않는지가 핵심 — fraud_case_search_port를 안 주거나, 위험 정황이
# 없거나, 검색이 빈 리스트를 반환하는 세 가지 경우 모두 판정 자체는 그대로 통과해야 한다.

from application.services import CallAnalysisService
from domain.entities import (
    CallAnalysisResult,
    DetectedPattern,
    PatternCategory,
    PatternDetectionResult,
    RiskAssessment,
    RiskExplanation,
    RiskLevel,
    SimilarCase,
)


def _high_risk_result() -> CallAnalysisResult:
    detection = PatternDetectionResult(
        transcript="검찰청인데 안전계좌로 이체하세요",
        detected_patterns=[DetectedPattern(category=PatternCategory.AUTHORITY_IMPERSONATION, matched_keywords=["검찰청"])],
    )
    risk = RiskAssessment(score=95, level=RiskLevel.HIGH, breakdown=[])
    explanation = RiskExplanation(summary="고위험 등급 (위험도 95점)", reasons=["[기관사칭] ..."], narrative="고위험 등급 (위험도 95점)\n\n근거:\n- [기관사칭] ...")
    return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)


def _benign_result() -> CallAnalysisResult:
    detection = PatternDetectionResult(transcript="내일 회의 시간 확인차 연락드렸습니다.", detected_patterns=[])
    risk = RiskAssessment(score=0, level=RiskLevel.LOW, breakdown=[])
    explanation = RiskExplanation(summary="저위험 등급 (위험도 0점)", reasons=[], narrative="저위험 등급 (위험도 0점)")
    return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)


class _FakeCallAnalysisPort:
    def __init__(self, result: CallAnalysisResult):
        self._result = result

    def analyze(self, transcript: str) -> CallAnalysisResult:
        return self._result


class _FakeFraudCaseSearchPort:
    def __init__(self, cases: list[SimilarCase]):
        self._cases = cases
        self.received: tuple[str, int] | None = None

    def search(self, transcript: str, top_k: int) -> list[SimilarCase]:
        self.received = (transcript, top_k)
        return self._cases


_SAMPLE_CASE = SimilarCase(
    case_id="case-1",
    title="검찰 사칭 안전계좌 편취",
    category="authority_impersonation",
    summary="검찰청을 사칭해 안전계좌로 이체를 유도한 사례",
    source_note="경찰청 보도자료 요약",
    similarity=0.87,
)


def test_similar_cases_are_merged_into_explanation_when_risk_detected():
    service = CallAnalysisService(_FakeCallAnalysisPort(_high_risk_result()), _FakeFraudCaseSearchPort([_SAMPLE_CASE]))

    result = service.execute("검찰청인데 안전계좌로 이체하세요")

    assert result.similar_cases == [_SAMPLE_CASE]
    assert any("검찰 사칭 안전계좌 편취" in r for r in result.explanation.reasons)
    assert "87%" in result.explanation.narrative
    # 기존 판정 근거(F-01/F-02)는 그대로 유지되어야 한다
    assert "[기관사칭] ..." in result.explanation.reasons


def test_search_is_skipped_when_no_risk_indicators():
    port = _FakeFraudCaseSearchPort([_SAMPLE_CASE])
    service = CallAnalysisService(_FakeCallAnalysisPort(_benign_result()), port)

    result = service.execute("내일 회의 시간 확인차 연락드렸습니다.")

    assert result.similar_cases == []
    assert port.received is None  # 위험 정황이 없으면 rag-worker를 아예 부르지 않는다


def test_analysis_is_unaffected_without_fraud_case_search_port():
    base_result = _high_risk_result()
    service = CallAnalysisService(_FakeCallAnalysisPort(base_result))

    result = service.execute("검찰청인데 안전계좌로 이체하세요")

    assert result is base_result
    assert result.similar_cases == []


def test_analysis_is_unaffected_when_search_returns_no_matches():
    """RagWorkerSearchAdapter는 rag-worker가 죽어 있어도 예외 없이 빈 리스트를 반환한다
    (infrastructure/adapters/rag_worker_search_adapter.py 참고) — 여기서는 그 빈 결과를
    받았을 때도 판정 자체가 그대로 유지되는지만 확인한다."""
    base_result = _high_risk_result()
    service = CallAnalysisService(_FakeCallAnalysisPort(base_result), _FakeFraudCaseSearchPort([]))

    result = service.execute("검찰청인데 안전계좌로 이체하세요")

    assert result is base_result
