# F-04: mcp-server 응답의 similar_cases가 AnalyzeCallService를 통해 도메인 모델로
# 올바르게 매핑되는지 확인한다. 실제 mcp-server 판정/결합 로직 자체는 mcp-server 쪽
# (test_call_analysis_similar_cases.py)에서 이미 검증되므로, 여기서는 api의 매핑 책임만 본다.

import asyncio

from src.application.services import AnalyzeCallService
from src.infrastructure.adapters.in_memory_call_log import InMemoryCallLogRepository


class _FakeCallAnalysisPortWithSimilarCases:
    def analyze(self, transcript: str, channel: str = "call") -> dict:
        return {
            "risk_score": 95,
            "risk_level": "high",
            "detected_patterns": [],
            "explanation_summary": "요약",
            "explanation": "근거",
            "similar_cases": [
                {
                    "case_id": "case-1",
                    "title": "검찰 사칭 안전계좌 편취",
                    "category": "authority_impersonation",
                    "summary": "검찰청을 사칭해 안전계좌로 이체를 유도한 사례",
                    "source_note": "경찰청 보도자료 요약",
                    "similarity": 0.87,
                }
            ],
        }


class _FakeCallAnalysisPortWithoutSimilarCasesKey:
    """구버전 mcp-server(응답에 similar_cases 필드가 없던 시절) 호환성 확인용."""

    def analyze(self, transcript: str, channel: str = "call") -> dict:
        return {
            "risk_score": 0,
            "risk_level": "low",
            "detected_patterns": [],
            "explanation_summary": "요약",
            "explanation": "근거",
        }


def test_similar_cases_are_mapped_onto_domain_result():
    service = AnalyzeCallService(_FakeCallAnalysisPortWithSimilarCases(), InMemoryCallLogRepository())

    result = asyncio.run(service.execute("검찰청인데 안전계좌로 이체하세요"))

    assert len(result.similar_cases) == 1
    assert result.similar_cases[0].title == "검찰 사칭 안전계좌 편취"
    assert result.similar_cases[0].similarity == 0.87


def test_missing_similar_cases_key_defaults_to_empty_list():
    service = AnalyzeCallService(_FakeCallAnalysisPortWithoutSimilarCasesKey(), InMemoryCallLogRepository())

    result = asyncio.run(service.execute("안녕하세요"))

    assert result.similar_cases == []
