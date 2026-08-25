# F-01/F-02/F-05 v1 구현체: 키워드 규칙 기반(PatternDetectionService/RiskScoringService/
# ExplanationService, application/services.py 참고)을 CallAnalysisPort로 감싼다.
#
# 이 어댑터는 두 가지 역할을 한다:
#   1) LLM_DEBUG_COMPARE=1일 때 OllamaCallAnalysisAdapter와 결과를 비교하는 기준선
#   2) Ollama 호출이 실패(타임아웃/모델 미로드/JSON 파싱 실패)했을 때의 안전 폴백
#      (OllamaCallAnalysisAdapter가 생성자에서 이 어댑터를 받아 내부적으로 위임한다)

from domain.entities import CallAnalysisResult
from application.services import ExplanationService, PatternDetectionService, RiskScoringService


class RuleBasedCallAnalysisAdapter:
    def __init__(self):
        self._detection_service = PatternDetectionService()
        self._scoring_service = RiskScoringService()
        self._explanation_service = ExplanationService()

    def analyze(self, transcript: str) -> CallAnalysisResult:
        detection = self._detection_service.detect(transcript)
        risk = self._scoring_service.score(detection)
        explanation = self._explanation_service.generate(detection, risk)
        return CallAnalysisResult(detection=detection, risk=risk, explanation=explanation)
