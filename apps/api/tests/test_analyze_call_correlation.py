# 우선순위 2(크로스채널 상관관계 탐지)가 AnalyzeCallService에 올바르게 결합되는지
# 검증한다. test_analyze_call_similar_cases.py와 같은 패턴 — 가짜 포트로 실제
# mcp-server 없이 오케스트레이션만 확인한다. 실제 상관관계 매칭 로직 자체는
# apps/mcp-server 쪽에서 이미 검증했다.

import asyncio

from src.application.services import AnalyzeCallService
from src.infrastructure.adapters.in_memory_call_log import InMemoryCallLogRepository


def _base_raw(**overrides) -> dict:
    base = {
        "risk_score": 35,
        "risk_level": "low",
        "detected_patterns": [],
        "explanation_summary": "저위험 등급 (위험도 35점) — 경미한 의심 정황.",
        "explanation_reasons": ["[긴급송금유도] ..."],
        "explanation": "저위험 등급 (위험도 35점) — 경미한 의심 정황.\n\n근거:\n- [긴급송금유도] ...",
    }
    base.update(overrides)
    return base


class _FakeCallAnalysisPort:
    def __init__(self, raw: dict):
        self._raw = raw

    def analyze(self, transcript: str, channel: str = "call") -> dict:
        return self._raw


class _FakeCorrelationPort:
    def __init__(self, result: dict):
        self._result = result
        self.received: dict | None = None

    def correlate(self, channel, entities, occurred_at, context_excerpt, current_risk_score, source_ref=None) -> dict:
        self.received = {
            "channel": channel,
            "entities": entities,
            "current_risk_score": current_risk_score,
            "context_excerpt": context_excerpt,
            "source_ref": source_ref,
        }
        return self._result


_MATCH_REASON = "12분 전 문자 채널에서 동일 전화번호(*******5678)이(가) 감지되었습니다 — 크로스채널 상관관계"

_MATCH_RESULT = {
    "matches": [
        {
            "entity_type": "phone",
            "entity_value": "*******5678",
            "matched_channel": "sms",
            "matched_at": "2026-09-02T11:48:00+00:00",
            "source_ref": "other-call-id-123",
            "reason": _MATCH_REASON,
        }
    ],
    "match_count": 1,
    "risk_boost": 15,
    "reasons": [_MATCH_REASON],
    "updated_risk_score": 50,
    "updated_risk_level": "medium",
}

_NO_MATCH_RESULT = {
    "matches": [],
    "match_count": 0,
    "risk_boost": 0,
    "reasons": [],
    "updated_risk_score": 35,
    "updated_risk_level": "low",
}


def test_correlation_match_raises_score_and_appends_reason():
    correlation_port = _FakeCorrelationPort(_MATCH_RESULT)
    service = AnalyzeCallService(
        _FakeCallAnalysisPort(_base_raw()), InMemoryCallLogRepository(), correlation_port
    )

    result = asyncio.run(service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다"))

    assert result.risk_score == 50
    assert result.risk_level.value == "medium"
    assert any("크로스채널 상관관계" in r for r in result.explanation.split("\n"))
    assert "[긴급송금유도] ..." in result.explanation  # 기존 근거 유지

    # F-06 대시보드 item 1: 원점수/가산분/최종점수가 자연어로 드러나야 한다(내부 로직 문구 금지).
    assert "35점 + 크로스채널 근거 15점 → 50점" in result.explanation_summary
    assert result.base_risk_score == 35

    # F-06 대시보드 item 2: 구조화된 근거 + 클릭 이동용 call_id가 채워져야 한다.
    assert len(result.correlation_matches) == 1
    assert result.correlation_matches[0].reason == _MATCH_REASON
    assert result.correlation_matches[0].source_call_id == "other-call-id-123"

    # F-06 대시보드 item 2: correlate()에 이번 판정 자신의 call_id를 source_ref로 넘겨야
    # 나중에 다른 채널이 이 판정을 근거로 인용할 때 클릭 이동할 수 있다.
    assert correlation_port.received["source_ref"] == result.call_id


def test_no_match_leaves_score_unchanged():
    correlation_port = _FakeCorrelationPort(_NO_MATCH_RESULT)
    service = AnalyzeCallService(
        _FakeCallAnalysisPort(_base_raw()), InMemoryCallLogRepository(), correlation_port
    )

    result = asyncio.run(service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다"))

    assert result.risk_score == 35
    assert result.risk_level.value == "low"
    assert result.base_risk_score == 35
    assert result.correlation_matches == []


def test_transcript_without_entities_skips_correlation_call():
    correlation_port = _FakeCorrelationPort(_MATCH_RESULT)
    service = AnalyzeCallService(
        _FakeCallAnalysisPort(_base_raw()), InMemoryCallLogRepository(), correlation_port
    )

    result = asyncio.run(service.execute("내일 회의 시간 확인차 연락드렸습니다."))

    assert correlation_port.received is None
    assert result.risk_score == 35


def test_correlation_receives_entities_extracted_from_raw_transcript_not_masked():
    """N-03과의 상호작용 핵심: mask_pii()가 지우기 전 원문에서 추출해야 전화번호가
    실제로 잡힌다(masked_transcript에는 "[전화번호]" 태그만 남아 추출할 값이 없음)."""
    correlation_port = _FakeCorrelationPort(_NO_MATCH_RESULT)
    service = AnalyzeCallService(
        _FakeCallAnalysisPort(_base_raw()), InMemoryCallLogRepository(), correlation_port
    )

    asyncio.run(service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다"))

    assert correlation_port.received is not None
    assert {"entity_type": "phone", "value": "01012345678"} in correlation_port.received["entities"]
    assert correlation_port.received["current_risk_score"] == 35


def test_analysis_is_unaffected_without_correlation_port():
    service = AnalyzeCallService(_FakeCallAnalysisPort(_base_raw()), InMemoryCallLogRepository())

    result = asyncio.run(service.execute("010-1234-5678로 안전계좌 이체 부탁드립니다"))

    assert result.risk_score == 35
