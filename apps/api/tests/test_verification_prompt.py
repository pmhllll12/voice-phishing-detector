# 역방향 신원확인 POC: verification_prompt 판단 로직(domain/identity_verification.py) 단위 테스트.
# "AI가 의심하고, 신분증이 확정한다" — 이 함수는 의심(안내 여부)만 결정한다.

from datetime import datetime, timezone

from src.domain.entities import CallAnalysisResult, DetectedPatternSummary, RiskLevel
from src.domain.identity_verification import decide_verification_prompt


def _result(risk_level: RiskLevel, risk_score: int, categories: list[str], keywords: list[str] | None = None):
    return CallAnalysisResult(
        call_id="call-1",
        raw_transcript="원문",
        masked_transcript="마스킹",
        risk_score=risk_score,
        risk_level=risk_level,
        detected_patterns=[
            DetectedPatternSummary(category=c, category_label=c, matched_keywords=keywords or []) for c in categories
        ],
        explanation_summary="요약",
        explanation="근거",
        analyzed_at=datetime(2026, 10, 12, tzinfo=timezone.utc),
    )


def test_authority_impersonation_requires_verification_even_at_low_risk():
    prompt = decide_verification_prompt(
        _result(RiskLevel.LOW, 20, ["authority_impersonation"], keywords=["검찰", "수사관"])
    )

    assert prompt.required is True
    # N-04: 왜 안내하는지(탐지된 표현)가 문구에 들어간다
    assert "검찰" in prompt.message and "기관사칭" in prompt.message


def test_high_risk_without_impersonation_requires_verification():
    prompt = decide_verification_prompt(_result(RiskLevel.HIGH, 85, ["urgent_transfer"]))

    assert prompt.required is True
    assert "고위험(85점)" in prompt.message


def test_medium_risk_without_impersonation_does_not_require_verification():
    prompt = decide_verification_prompt(_result(RiskLevel.MEDIUM, 55, ["fear_inducement"]))

    assert prompt.required is False
    assert prompt.message is None


def test_low_risk_without_patterns_does_not_require_verification():
    prompt = decide_verification_prompt(_result(RiskLevel.LOW, 0, []))

    assert prompt.required is False
