# application 계층: analyze_call_pattern 결과를 바깥으로 내보내는 공용 직렬화.
#
# server.py(MCP stdio 툴, Claude Code용)와 rest_server.py(일반 HTTP REST, apps/api용)
# 두 어댑터가 같은 application 서비스(PatternDetectionService/RiskScoringService/
# ExplanationService)를 감싸면서 이 함수를 공유한다 — 판정 로직과 응답 형식이 두 어댑터
# 사이에서 벌어지지 않도록.

from domain.entities import PatternDetectionResult, RiskAssessment, RiskExplanation


def serialize_analysis(
    result: PatternDetectionResult, risk: RiskAssessment, explanation: RiskExplanation
) -> dict:
    return {
        "detected_patterns": [
            {
                "category": p.category.value,
                "category_label": p.category_label,
                "matched_keywords": p.matched_keywords,
            }
            for p in result.detected_patterns
        ],
        "pattern_count": len(result.detected_patterns),
        "has_risk_indicators": result.has_risk_indicators,
        "risk_score": risk.score,
        "risk_level": risk.level.value,
        "explanation_summary": explanation.summary,
        "explanation_reasons": explanation.reasons,
        "explanation": explanation.narrative,
    }
