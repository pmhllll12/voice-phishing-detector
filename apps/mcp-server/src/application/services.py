# application 계층: F-01/F-02/F-05/F-07 유스케이스.
# domain의 규칙만 사용하고 mcp 패키지 등 외부 프레임워크는 모른다 — 그래야 이
# 서비스만 따로 단위 테스트할 수 있다 (tests/ 참고).

import uuid
from datetime import datetime, timezone

from domain.entities import (
    DetectedPattern,
    PatternDetectionResult,
    ReportRecord,
    RiskAssessment,
    RiskExplanation,
    RiskLevel,
    RiskScoreBreakdownItem,
    RISK_LEVEL_LABELS,
    RISK_LEVEL_THRESHOLDS,
)
from domain.pattern_rules import CATEGORY_WEIGHTS, PATTERN_RULES
from domain.ports import ReportRepositoryPort


class PatternDetectionService:
    """F-01: 키워드 기반 규칙으로 통화/문자 텍스트의 보이스피싱 패턴을 탐지한다.

    TODO (고도화 순서 제안):
      1. (완료) 키워드 매칭 기반 1차 구현
      2. 오탐(false positive) 검증 — 합성 데이터셋으로 정밀도/재현율 측정
      3. 문맥 이해가 필요한 사례 대응을 위해 LLM 기반 분류로 전환 검토
      4. (완료) F-02: RiskScoringService에서 이 결과에 가중치를 부여해 점수화
      5. F-05: matched_keywords를 판정 근거 문장 생성에 그대로 활용
    """

    def detect(self, transcript: str) -> PatternDetectionResult:
        detected: list[DetectedPattern] = []

        for category, keywords in PATTERN_RULES.items():
            matched = [kw for kw in keywords if kw in transcript]
            if matched:
                detected.append(DetectedPattern(category=category, matched_keywords=matched))

        return PatternDetectionResult(transcript=transcript, detected_patterns=detected)


class RiskScoringService:
    """F-02: PatternDetectionResult를 받아 0~100점 위험도 점수와 저/중/고 등급을 산출한다.

    TODO (고도화 순서 제안):
      1. (완료) 카테고리별 고정 가중치 합산 방식으로 1차 구현
      2. 합성 데이터셋으로 점수 분포를 검증하고 가중치/임계값(RISK_LEVEL_THRESHOLDS) 보정
      3. 매칭 키워드 개수, 반복 등장 등 추가 신호 반영 검토
      4. N-05(응답 5초 이내) SLA 계측 — infrastructure 계층에서
         vps_analysis_duration_seconds 메트릭으로 이 서비스 호출 시간을 측정할 예정
    """

    def score(self, detection_result: PatternDetectionResult) -> RiskAssessment:
        breakdown = [
            RiskScoreBreakdownItem(category=p.category, weight=CATEGORY_WEIGHTS[p.category])
            for p in detection_result.detected_patterns
        ]
        raw_score = sum(item.weight for item in breakdown)
        score = min(raw_score, 100)

        return RiskAssessment(score=score, level=self._level_for(score), breakdown=breakdown)

    @staticmethod
    def _level_for(score: int) -> RiskLevel:
        for threshold, level in RISK_LEVEL_THRESHOLDS:
            if score >= threshold:
                return level
        return RiskLevel.LOW


_VERDICT_SENTENCES: dict[RiskLevel, str] = {
    RiskLevel.HIGH: "보이스피싱 의심 정황이 다수 확인되어 즉각적인 주의가 필요합니다.",
    RiskLevel.MEDIUM: "보이스피싱 의심 정황이 일부 확인되어 주의가 필요합니다.",
    RiskLevel.LOW: "경미한 의심 정황이 확인되었으나 현재 위험도는 낮습니다.",
}

_NO_RISK_SENTENCE = "뚜렷한 보이스피싱 의심 정황이 확인되지 않았습니다."

_MAX_KEYWORDS_PER_REASON = 3


class ExplanationService:
    """F-05/N-04: 탐지 결과(F-01)와 위험도 평가(F-02)를 결합해 판정 근거를 자연어로 설명한다.

    "블랙박스 판정 불가"(N-04) 원칙에 따라, 모든 문장은 실제로 매칭된 키워드와
    카테고리별 가중치를 그대로 인용한다 — 점수만 던지지 않고 "왜" 그 점수인지 추적 가능하게.

    TODO (고도화 순서 제안):
      1. (완료) 템플릿 기반 규칙형 문장 생성으로 1차 구현
      2. F-04(유사사례) 결과를 근거 문장에 추가 결합하는 옵션 검토
         (지금은 analyze_call_pattern이 rag-worker 없이도 독립적으로 동작하도록
          의도적으로 F-04와 분리해뒀다)
      3. LLM 기반으로 더 자연스러운 문장 생성 검토 (단, 매칭 근거 인용은 계속 유지해야 함)
    """

    def generate(self, detection_result: PatternDetectionResult, risk: RiskAssessment) -> RiskExplanation:
        level_label = RISK_LEVEL_LABELS[risk.level]

        if not detection_result.has_risk_indicators:
            summary = f"{level_label} 등급 (위험도 {risk.score}점) — {_NO_RISK_SENTENCE}"
            return RiskExplanation(summary=summary, reasons=[], narrative=summary)

        reasons = [self._reason_for(pattern) for pattern in detection_result.detected_patterns]
        summary = f"{level_label} 등급 (위험도 {risk.score}점) — {_VERDICT_SENTENCES[risk.level]}"
        narrative = summary + "\n\n근거:\n" + "\n".join(f"- {r}" for r in reasons)

        return RiskExplanation(summary=summary, reasons=reasons, narrative=narrative)

    @staticmethod
    def _reason_for(pattern: DetectedPattern) -> str:
        weight = CATEGORY_WEIGHTS[pattern.category]
        shown_keywords = pattern.matched_keywords[:_MAX_KEYWORDS_PER_REASON]
        keyword_text = "、".join(shown_keywords)
        remaining = len(pattern.matched_keywords) - len(shown_keywords)
        if remaining > 0:
            keyword_text += f" 외 {remaining}건"
        return f"[{pattern.category_label}] 관련 표현이 감지되었습니다 (예: {keyword_text}) — 가중치 {weight}점"


class ReportSubmissionService:
    """F-07: 고위험 판정 시 신고 접수 프로세스를 개시한다 (mock).

    RFP 데이터 제약: 가상 프로젝트이므로 실제 112/경찰청 신고 API는 호출하지 않는다.
    "신고 접수 프로세스가 개시됐다"는 사실을 감사증적(현재는 인메모리)에 남기고
    report_id를 발급하는 수준까지만 구현한다.

    TODO:
      1. 실제 배포라면 채널 라우팅 정책을 명확히 정의 (지금은 risk_level == HIGH만
         "auto", 나머지는 "manual"로 단순 분기)
      2. 알림 발송(이메일/슬랙 등) 연동 — F-07의 "알림" 부분은 아직 mock에 없음
      3. N-01 감사증적과 통합 — 지금은 mcp-server 프로세스 메모리에만 별도로 쌓임
         (apps/api의 CallAnalysisResult 감사로그와 분리되어 있음)
    """

    def __init__(self, report_repository: ReportRepositoryPort):
        self._report_repository = report_repository

    def submit(self, case_summary: str, risk_level: RiskLevel) -> ReportRecord:
        channel = "auto" if risk_level == RiskLevel.HIGH else "manual"
        record = ReportRecord(
            report_id=str(uuid.uuid4()),
            case_summary=case_summary,
            risk_level=risk_level,
            channel=channel,
            status="submitted",
            submitted_at=datetime.now(timezone.utc),
        )
        self._report_repository.add(record)
        return record
