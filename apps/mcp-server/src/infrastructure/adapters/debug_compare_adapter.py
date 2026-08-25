# F-01/F-02 성능 비교용 디버그 래퍼. apps/rag-worker의 DebugCompareAdapter와 같은
# 패턴이다 (두 프로젝트가 별도 배포 단위/venv라 파일을 공유하진 않고 구조만 따라감):
# LLM(v2)과 규칙 기반(v1)을 같은 입력으로 모두 돌려서 점수 차이를 로그로 남긴다.
# 실제 응답은 LLM(primary) 결과를 쓴다. CallAnalysisPort를 구현하므로
# server.py/rest_server.py는 이 래퍼로 감싸든 안 감싸든 몰라도 된다.

import logging

from domain.entities import CallAnalysisResult
from domain.ports import CallAnalysisPort

logger = logging.getLogger(__name__)


class DebugCompareAdapter:
    def __init__(self, primary: CallAnalysisPort, comparison: CallAnalysisPort, comparison_label: str = "rule"):
        self._primary = primary
        self._comparison = comparison
        self._comparison_label = comparison_label

    def analyze(self, transcript: str) -> CallAnalysisResult:
        primary_result = self._primary.analyze(transcript)
        comparison_result = self._comparison.analyze(transcript)
        self._log_comparison(transcript, primary_result, comparison_result)
        return primary_result

    def _log_comparison(
        self, transcript: str, primary_result: CallAnalysisResult, comparison_result: CallAnalysisResult
    ) -> None:
        primary_categories = [p.category.value for p in primary_result.detection.detected_patterns]
        comparison_categories = [p.category.value for p in comparison_result.detection.detected_patterns]
        logger.info(
            "[F-01/F-02 debug-compare] transcript=%r\n"
            "  llm  : score=%d level=%s categories=%s\n"
            "  %-4s : score=%d level=%s categories=%s",
            transcript,
            primary_result.risk.score,
            primary_result.risk.level.value,
            primary_categories,
            self._comparison_label,
            comparison_result.risk.score,
            comparison_result.risk.level.value,
            comparison_categories,
        )
