# application 계층: F-01/F-02/F-05/F-07 유스케이스.
# domain의 규칙만 사용하고 mcp 패키지 등 외부 프레임워크는 모른다 — 그래야 이
# 서비스만 따로 단위 테스트할 수 있다 (tests/ 참고).

import uuid
from datetime import datetime, timezone

from domain.entities import (
    CallAnalysisResult,
    Channel,
    ChannelSignal,
    CorrelationMatch,
    CorrelationResult,
    DetectedPattern,
    EmailMessage,
    EntityType,
    ExtractedEntity,
    PatternDetectionResult,
    ReportRecord,
    RiskAssessment,
    RiskExplanation,
    RiskLevel,
    RiskScoreBreakdownItem,
    SimilarCase,
    CHANNEL_LABELS,
    ENTITY_TYPE_LABELS,
    RISK_LEVEL_LABELS,
    risk_level_for_score,
)
from domain.entity_extraction import extract_entities
from domain.pattern_rules import CATEGORY_WEIGHTS, PATTERN_RULES
from domain.ports import (
    CallAnalysisPort,
    ChannelSignalRepositoryPort,
    EmailSourcePort,
    FraudCaseSearchPort,
    ReportRepositoryPort,
    ThreatIntelligencePort,
)


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
        return risk_level_for_score(score)


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
      2. (완료) F-04(유사사례) 결과를 근거 문장에 추가 결합 — 다만 이 서비스 자체는
         여전히 rag-worker를 모른다. 결합은 CallAnalysisService.execute()가 이
         메서드의 결과를 받은 뒤 별도로 수행한다(아래 참고) — analyze_call_pattern이
         rag-worker 없이도 독립적으로 동작해야 한다는 원칙은 그대로 유지된다.
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


_MAX_SIMILAR_CASES_IN_EXPLANATION = 2


def _merge_similar_cases_into_explanation(
    explanation: RiskExplanation, similar_cases: list[SimilarCase]
) -> RiskExplanation:
    """F-04 검색 결과를 F-05 근거 문장에 추가 인용한다 (N-04: 유사도까지 그대로 노출해
    추적 가능하게)."""
    case_reasons = [
        f"유사 사례: 「{c.title}」(유사도 {c.similarity:.0%}) — {c.summary}" for c in similar_cases
    ]
    narrative = explanation.narrative + "\n\n유사 사례:\n" + "\n".join(f"- {r}" for r in case_reasons)
    return RiskExplanation(
        summary=explanation.summary,
        reasons=explanation.reasons + case_reasons,
        narrative=narrative,
    )


# 우선순위 2(크로스채널 상관관계 탐지, 2026-09-02): 동일 전화번호/계좌번호/URL이 서로
# 다른 채널의 탐지 기록에 시간 윈도우 안에 등장하면 위험도에 가산점을 준다. 시중 어떤
# 보이스피싱 차단 앱도 자기 채널 밖을 못 본다는 게 이 프로젝트의 차별점(README 참고).
_DEFAULT_CORRELATION_WINDOW_SECONDS = 30 * 60  # 30분 — 전화→문자→이메일 다단계 공격 시나리오 기준
_CORRELATION_RISK_BOOST_PER_MATCH = 15
_CORRELATION_RISK_BOOST_CAP = 30  # 엔티티가 여러 개 겹쳐도 무한정 커지지 않도록 상한
# 우선순위 2(선택 항목, 2026-09-02): Google Safe Browsing에 등록된 악성 URL로 확인되면
# 채널 재등장 여부와 무관하게 그 자체로 강한 위험 신호다(외부 기관이 이미 검증한
# 사실이라 채널 재등장 추정보다 신뢰도가 높음) — 그래서 가중치를 더 크게 둔다. URL이
# 몇 개든 플래그 자체는 한 번만 가산한다(여러 개 걸렸다고 위험도가 비례해 커질 필요는
# 없음 — 이미 하나만으로도 충분히 강한 신호).
_MALICIOUS_URL_RISK_BOOST = 40


def _mask_for_display(entity_type: EntityType, value: str) -> str:
    """channel_signals에는 원본 값을 저장하지만(매칭 정확도를 위해 필수), API/툴
    응답으로 나가는 값은 항상 마스킹한다 — N-03(개인정보 마스킹)과 같은 원칙. 이
    기능은 raw_transcript처럼 ADMIN 전용 원문 노출 경로를 아직 두지 않았다(범위 밖,
    필요해지면 N-02 RBAC과 결합해 추가 검토)."""
    if entity_type == EntityType.URL:
        return value  # host만 남긴 값이라 이미 PII가 아님(entity_extraction._normalize_url 참고)
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _reason_for_match(match: CorrelationMatch, occurred_at: datetime) -> str:
    gap_minutes = round(abs((occurred_at - match.matched_at).total_seconds()) / 60)
    order = "전" if match.matched_at <= occurred_at else "후"
    channel_label = CHANNEL_LABELS[match.matched_channel]
    entity_label = ENTITY_TYPE_LABELS[match.entity_type]
    return (
        f"{gap_minutes}분 {order} {channel_label} 채널에서 동일 {entity_label}"
        f"({match.entity_value})이(가) 감지되었습니다 — 크로스채널 상관관계"
    )


def _reason_for_malicious_url(url: str) -> str:
    return f"URL({url})이 Google Safe Browsing에 등록된 악성 사이트로 확인되었습니다 — 외부 위협 인텔리전스 연동"


class MultichannelCorrelationService:
    """우선순위 2 진입점. ChannelSignalRepositoryPort로 저장/조회를 위임한다 —
    CallAnalysisService가 F-01/F-02/F-05 로직을 모르고 포트만 아는 것과 같은 패턴.

    correlate()는 항상 이번 이벤트를 채널 신호로 "기록"도 한다 — 그래야 이후 다른
    채널 이벤트가 이걸 찾을 수 있다. 조회를 기록보다 먼저 해서 자기 자신과는
    매칭되지 않게 한다.

    threat_intelligence_port가 주어지면(선택, Google Safe Browsing), URL 엔티티를
    외부 위협 인텔리전스와 대조한다 — 이 검사는 크로스채널 매치 여부와 무관하게
    항상 수행된다(첫 등장이어도 이미 알려진 악성 URL이면 그 자체로 위험하다).
    """

    def __init__(
        self,
        repository: ChannelSignalRepositoryPort,
        window_seconds: int = _DEFAULT_CORRELATION_WINDOW_SECONDS,
        threat_intelligence_port: ThreatIntelligencePort | None = None,
    ):
        self._repository = repository
        self._window_seconds = window_seconds
        self._threat_intelligence_port = threat_intelligence_port

    def correlate(
        self,
        channel: Channel,
        entities: list[ExtractedEntity],
        occurred_at: datetime,
        context_excerpt: str,
        current_risk_score: int | None = None,
    ) -> CorrelationResult:
        if not entities:
            return CorrelationResult(
                updated_risk_score=current_risk_score,
                updated_risk_level=risk_level_for_score(current_risk_score) if current_risk_score is not None else None,
            )

        matches = self._repository.find_matches(entities, channel, occurred_at, self._window_seconds)
        self._repository.record(
            ChannelSignal(channel=channel, entities=entities, occurred_at=occurred_at, context_excerpt=context_excerpt)
        )

        flagged_urls: list[str] = []
        if self._threat_intelligence_port is not None:
            urls = [e.value for e in entities if e.entity_type == EntityType.URL]
            if urls:
                flagged_urls = self._threat_intelligence_port.check_urls(urls)

        if not matches and not flagged_urls:
            return CorrelationResult(
                updated_risk_score=current_risk_score,
                updated_risk_level=risk_level_for_score(current_risk_score) if current_risk_score is not None else None,
            )

        masked_matches = [
            CorrelationMatch(
                entity_type=m.entity_type,
                entity_value=_mask_for_display(m.entity_type, m.entity_value),
                matched_channel=m.matched_channel,
                matched_at=m.matched_at,
                context_excerpt=m.context_excerpt,
            )
            for m in matches
        ]
        channel_boost = min(len(masked_matches) * _CORRELATION_RISK_BOOST_PER_MATCH, _CORRELATION_RISK_BOOST_CAP)
        malicious_boost = _MALICIOUS_URL_RISK_BOOST if flagged_urls else 0
        boost = channel_boost + malicious_boost

        reasons = [_reason_for_match(m, occurred_at) for m in masked_matches]
        reasons += [_reason_for_malicious_url(url) for url in flagged_urls]

        updated_score = None
        updated_level = None
        if current_risk_score is not None:
            updated_score = min(100, current_risk_score + boost)
            updated_level = risk_level_for_score(updated_score)

        return CorrelationResult(
            matches=masked_matches,
            flagged_urls=flagged_urls,
            risk_boost=boost,
            reasons=reasons,
            updated_risk_score=updated_score,
            updated_risk_level=updated_level,
        )


def _merge_correlation_into_explanation(explanation: RiskExplanation, correlation: CorrelationResult) -> RiskExplanation:
    """correlation.updated_risk_score/level이 이미 반영된 새 summary 문장을 explanation에
    합친다. narrative는 항상 summary로 시작한다는 불변식(ExplanationService.generate/
    _merge_similar_cases_into_explanation 참고)을 이용해 앞부분만 새 summary로 교체한다."""
    level_label = RISK_LEVEL_LABELS[correlation.updated_risk_level]
    new_summary = (
        f"{level_label} 등급 (위험도 {correlation.updated_risk_score}점, "
        f"크로스채널 상관관계 +{correlation.risk_boost}점 포함) — {_VERDICT_SENTENCES[correlation.updated_risk_level]}"
    )
    rest = explanation.narrative[len(explanation.summary):]
    narrative = new_summary + rest + "\n\n크로스채널 상관관계:\n" + "\n".join(f"- {r}" for r in correlation.reasons)
    return RiskExplanation(
        summary=new_summary,
        reasons=explanation.reasons + correlation.reasons,
        narrative=narrative,
    )


class CallAnalysisService:
    """F-01/F-02/F-05 진입점. CallAnalysisPort 구현체(규칙 기반 v1 또는 LLM 기반 v2,
    혹은 둘을 비교 로깅하는 래퍼)에 실제 판단을 위임한다 — F-04의
    SimilarCaseSearchService와 동일하게, 이 서비스 자체는 로직을 모르고 포트만 안다.
    server.py/rest_server.py는 이 서비스 하나만 호출하면 된다.

    fraud_case_search_port가 주어지면(F-04), 위험 정황이 감지된 경우에 한해 유사
    사례를 검색해 판정 근거(F-05)에 결합한다. 포트를 안 주거나(None) 검색이
    실패하면(RagWorkerSearchAdapter가 빈 리스트로 폴백) F-01/F-02/F-05만으로 정상
    동작한다 — rag-worker 의존은 어디까지나 "있으면 근거를 더 풍부하게" 수준이지
    필수 의존이 아니다.

    correlation_service가 주어지면(우선순위 2), 이 transcript에서 엔티티(전화번호/
    계좌번호/URL)를 추출해 call 채널 신호로 기록하고, 다른 채널에서 같은 엔티티가
    최근 발견됐으면 위험도 점수에 가산점을 주고 판정 근거에 근거 문장을 추가한다.

    ⚠️ 알려진 한계(N-03과의 상호작용): apps/api는 mcp-server를 호출하기 "전에"
    통화 텍스트를 마스킹한다(전화번호/계좌번호가 "[전화번호]"/"[계좌번호]" 태그로
    치환됨 — apps/api/src/domain/pii_masking.py 참고). 즉 REST 경로(apps/api →
    이 서비스)에서는 이 서비스가 받는 transcript 자체가 이미 마스킹된 뒤라, 전화번호/
    계좌번호 상관관계는 실질적으로 매칭되지 않는다(URL은 N-03이 마스킹 대상으로 삼지
    않아 그대로 작동한다). MCP stdio 직접 호출(Claude Code)이나
    correlate_multichannel_signals 툴로 원문을 직접 넣는 경로에서는 정상 작동한다.
    이 트레이드오프를 해소하려면 apps/api가 마스킹 "전" 원문에서 엔티티만 추출해
    (원문 전체가 아니라 엔티티 값만) mcp-server로 넘기는 별도 경로가 필요하다 —
    범위가 커서 이번 이터레이션에는 포함하지 않았다(README/design.md에 다음 과제로 명시).
    """

    def __init__(
        self,
        port: CallAnalysisPort,
        fraud_case_search_port: FraudCaseSearchPort | None = None,
        correlation_service: MultichannelCorrelationService | None = None,
    ):
        self._port = port
        self._fraud_case_search_port = fraud_case_search_port
        self._correlation_service = correlation_service

    def execute(
        self,
        transcript: str,
        channel: Channel = Channel.CALL,
        occurred_at: datetime | None = None,
    ) -> CallAnalysisResult:
        """channel/occurred_at은 우선순위 2(SMS/email 실채널 연동)를 위해 일반화했다 —
        기본값(CALL/now)은 기존 호출부(server.py/rest_server.py의 analyze_call_pattern)
        와 완전히 동일하게 동작한다. EmailIngestionService가 channel=EMAIL로 이 메서드를
        재사용해서, F-01/F-02/F-05 판정 로직을 이메일용으로 새로 만들지 않는다."""
        result = self._port.analyze(transcript)

        if self._fraud_case_search_port is not None and result.detection.has_risk_indicators:
            similar_cases = self._fraud_case_search_port.search(
                transcript, top_k=_MAX_SIMILAR_CASES_IN_EXPLANATION
            )
            if similar_cases:
                result = CallAnalysisResult(
                    detection=result.detection,
                    risk=result.risk,
                    explanation=_merge_similar_cases_into_explanation(result.explanation, similar_cases),
                    similar_cases=similar_cases,
                )

        if self._correlation_service is not None:
            entities = extract_entities(transcript)
            if entities:
                correlation = self._correlation_service.correlate(
                    channel,
                    entities,
                    occurred_at=occurred_at or datetime.now(timezone.utc),
                    context_excerpt=transcript[:200],
                    current_risk_score=result.risk.score,
                )
                # 크로스채널 매치가 없어도 악성 URL(flagged_urls)만으로 가산점이 붙을 수
                # 있다(Google Safe Browsing 연동) — matches만 보면 그 경우를 놓친다.
                if correlation.matches or correlation.flagged_urls:
                    new_risk = RiskAssessment(
                        score=correlation.updated_risk_score,
                        level=correlation.updated_risk_level,
                        breakdown=result.risk.breakdown,
                        correlation_boost=correlation.risk_boost,
                    )
                    result = CallAnalysisResult(
                        detection=result.detection,
                        risk=new_risk,
                        explanation=_merge_correlation_into_explanation(result.explanation, correlation),
                        similar_cases=result.similar_cases,
                    )

        return result


class EmailIngestionService:
    """우선순위 2(SMS/email 실채널 연동, 2026-09-02) — email만 실제 구현. SMS는 실제
    수신에 유료 SMS 게이트웨이(Twilio 등, 전화번호 임대+건당 과금)가 필요해 이번
    범위에서는 설계만 하고 실연동은 하지 않았다(docs/design.md 7장 참고).

    합성 데이터로 검증하던 크로스채널 상관관계(우선순위 2 1차 이터레이션)에 "진짜"
    email 채널 이벤트를 공급하는 유입 경로다. F-01/F-02/F-05 판정 로직을 이메일용
    으로 새로 만들지 않고, CallAnalysisService.execute()를 channel=Channel.EMAIL로
    재사용한다 — "통화든 문자든 이메일이든 텍스트 판정 로직은 같다"는 게 이 설계의
    핵심 전제(제목+본문을 합쳐 하나의 텍스트로 넘긴다).
    """

    def __init__(self, email_source: EmailSourcePort, call_analysis_service: CallAnalysisService):
        self._email_source = email_source
        self._call_analysis_service = call_analysis_service

    def poll_once(self) -> list[tuple[EmailMessage, CallAnalysisResult]]:
        """새 메일을 전부 가져와 판정하고 처리 완료 표시까지 한다. 판정 자체가
        예외를 던지면(예: 개별 메일 파싱 실패) 그 메일은 처리 완료 표시를 안 하고
        건너뛴다 — 다음 폴링에서 재시도된다."""
        results: list[tuple[EmailMessage, CallAnalysisResult]] = []
        for email in self._email_source.fetch_new_emails():
            text = f"{email.subject}\n\n{email.body}"
            analysis = self._call_analysis_service.execute(text, channel=Channel.EMAIL, occurred_at=email.received_at)
            results.append((email, analysis))
            self._email_source.mark_processed(email.message_id)
        return results


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
