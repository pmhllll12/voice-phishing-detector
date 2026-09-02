# application 계층: analyze_call_pattern 결과를 바깥으로 내보내는 공용 직렬화.
#
# server.py(MCP stdio 툴, Claude Code용)와 rest_server.py(일반 HTTP REST, apps/api용)
# 두 어댑터가 같은 application 서비스(PatternDetectionService/RiskScoringService/
# ExplanationService)를 감싸면서 이 함수를 공유한다 — 판정 로직과 응답 형식이 두 어댑터
# 사이에서 벌어지지 않도록.

from domain.entities import (
    CorrelationResult,
    PatternDetectionResult,
    ReportRecord,
    RiskAssessment,
    RiskExplanation,
    SimilarCase,
)


def serialize_analysis(
    result: PatternDetectionResult,
    risk: RiskAssessment,
    explanation: RiskExplanation,
    similar_cases: list[SimilarCase] | None = None,
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
        # 우선순위 2: risk.score에 이미 반영된 크로스채널 상관관계 가산점(N-04 추적가능성).
        "correlation_boost": risk.correlation_boost,
        "explanation_summary": explanation.summary,
        "explanation_reasons": explanation.reasons,
        "explanation": explanation.narrative,
        # F-04: 위험 정황이 없거나 rag-worker 검색이 실패하면 빈 리스트 — CallAnalysisService
        # 상단 주석 참고.
        "similar_cases": [
            {
                "case_id": c.case_id,
                "title": c.title,
                "category": c.category,
                "summary": c.summary,
                "source_note": c.source_note,
                "similarity": c.similarity,
            }
            for c in (similar_cases or [])
        ],
    }


def serialize_correlation(correlation: CorrelationResult) -> dict:
    """correlate_multichannel_signals 툴/REST 엔드포인트 응답. entity_value는 이미
    마스킹된 표시값이다(MultichannelCorrelationService._mask_for_display 참고)."""
    return {
        "matches": [
            {
                "entity_type": m.entity_type.value,
                "entity_value": m.entity_value,
                "matched_channel": m.matched_channel.value,
                "matched_at": m.matched_at.isoformat(),
            }
            for m in correlation.matches
        ],
        "match_count": len(correlation.matches),
        # 우선순위 2(선택 항목): Google Safe Browsing이 악성으로 확인한 URL(host만,
        # entity_extraction._normalize_url 참고 — 이미 PII가 아니라 마스킹하지 않음).
        "flagged_urls": correlation.flagged_urls,
        "risk_boost": correlation.risk_boost,
        "reasons": correlation.reasons,
        "updated_risk_score": correlation.updated_risk_score,
        "updated_risk_level": correlation.updated_risk_level.value if correlation.updated_risk_level else None,
    }


def serialize_report(record: ReportRecord) -> dict:
    """F-07: server.py(MCP 툴)와 rest_server.py(REST) 두 어댑터가 같은 응답 형식을
    쓰도록 공유한다 — serialize_analysis와 동일한 목적."""
    return {
        "report_id": record.report_id,
        "status": record.status,
        "channel": record.channel,
        "submitted_at": record.submitted_at.isoformat(),
        "note": "MOCK: 실제 112/경찰청 신고 API 연동 없음 (RFP 데이터 제약, docs/RFP.md 4장 참고)",
    }
