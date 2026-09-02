# application 계층: 유스케이스(비즈니스 프로세스)를 조합하는 곳.
# domain의 모델을 사용하되, 실제 DB/외부 API 호출은 infrastructure의 포트(인터페이스)를
# 통해서만 위임한다 — 그래야 이 계층을 테스트할 때 진짜 DB 없이도 테스트할 수 있다.

import uuid
from datetime import datetime, timezone

from src.domain.deepvoice import DeepvoiceVerdict
from src.domain.entities import (
    CallAnalysisResult,
    CorrelationMatchSummary,
    DetectedPatternSummary,
    RiskLevel,
    SimilarCaseSummary,
    StatsSummary,
)
from src.domain.entity_extraction import extract_entities
from src.domain.pii_masking import mask_pii
from src.domain.ports import (
    CallAnalysisPort,
    CallLogPort,
    DeepvoiceDetectionPort,
    MultichannelCorrelationPort,
    ReportPort,
    TranscriptionPort,
)

_RISK_LEVEL_LABELS = {"low": "저위험", "medium": "중위험", "high": "고위험"}


def _merge_correlation_into_raw(raw: dict, correlation: dict) -> dict:
    """mcp-server(/api/v1/correlate) 응답을 analyze 결과 dict에 결합한다. mcp-server
    내부의 CallAnalysisService(call 채널 자동 결합)와 달리 여기서는 응답의 summary
    문장 전체를 재생성하지 않는다 — 대신 원래 문장은 그대로 두고 상관관계로 바뀐
    점수/등급과 근거를 명시적으로 덧붙인다(N-04: 어느 쪽이 원래 판정이고 어느 쪽이
    상관관계로 추가된 것인지 구분되게).

    F-06 대시보드(2026-09-02): summary 접미사를 "내부 로직처럼 보이는" 표기
    ("+15점 반영, 최종 100점/고위험")에서 "원점수 + 가산 → 최종점수" 형태의
    자연어 표기로 바꿨다 — 평가자가 코드를 안 봐도 계산 과정을 읽을 수 있어야
    한다는 게 이번 작업 지시의 취지였다. 100점 상한에 걸려 실제 가산분이 표시된
    risk_boost보다 적게 반영된 경우 "(상한)"을 붙여 그 사실도 숨기지 않는다."""
    base_score = raw["risk_score"]
    updated_score = correlation["updated_risk_score"]
    updated_level = correlation["updated_risk_level"]
    reasons = correlation["reasons"]
    boost = correlation["risk_boost"]
    level_label = _RISK_LEVEL_LABELS.get(updated_level, updated_level)
    capped = "(상한)" if base_score + boost > 100 else ""

    merged = dict(raw)
    merged["risk_score"] = updated_score
    merged["risk_level"] = updated_level
    merged["explanation_summary"] = (
        raw["explanation_summary"] + f" ({base_score}점 + 크로스채널 근거 {boost}점 → "
        f"{updated_score}점{capped}, {level_label})"
    )
    merged["explanation_reasons"] = raw["explanation_reasons"] + reasons
    merged["explanation"] = raw["explanation"] + "\n\n크로스채널 상관관계:\n" + "\n".join(f"- {r}" for r in reasons)
    return merged


class AnalyzeCallService:
    """F-01/F-02/F-05 유스케이스: 통화/문자 텍스트를 mcp-server에 넘겨 판정받고,
    감사증적/대시보드용으로 저장한다.

    실제 탐지/스코어링/설명 로직은 여기 없다 — mcp-server(analyze_call_pattern)가
    이미 구현해뒀고(같은 로직을 두 번 만들지 않기 위해), 여기서는 그 결과를 도메인
    모델로 매핑하고 CallLogPort에 적재하는 오케스트레이션만 한다.

    TODO:
      1. (완료) F-04 rag-worker 유사사례 결과 결합 — mcp-server가 이미 결합해서
         내려주므로(raw["similar_cases"]) 여기서는 그대로 옮겨 담기만 한다.
      2. N-05 응답시간(5초) SLA 계측 — infrastructure/metrics.py의
         vps_analysis_duration_seconds 로 계측
      3. (완료) N-03 개인정보 마스킹 — mcp-server에 넘기기 전에 적용(아래 참고)
    """

    def __init__(
        self,
        call_analysis_port: CallAnalysisPort,
        call_log_port: CallLogPort,
        correlation_port: MultichannelCorrelationPort | None = None,
    ):
        self._call_analysis_port = call_analysis_port
        self._call_log_port = call_log_port
        self._correlation_port = correlation_port

    async def execute(
        self, transcript: str, channel: str = "call", occurred_at: datetime | None = None
    ) -> CallAnalysisResult:
        """channel/occurred_at은 SMS/email 실채널 연동(2026-09-02)을 위해 일반화했다 —
        기본값(call/None→now)은 기존 호출부(analyze_call 엔드포인트)와 완전히
        동일하게 동작한다. Gmail 폴러(apps/mcp-server/scripts/poll_gmail_inbox.py)가
        channel="email"로 이 메서드를 호출해, F-01/F-02 판정 로직을 새로 만들지
        않고 그대로 재사용하면서 감사증적/대시보드에도 이메일 판정이 남는다."""
        # F-06 대시보드 "근거 연결"(2026-09-02): call_id를 미리 발급해 correlate() 호출에
        # source_ref로 실어보낸다 — 그래야 나중에 다른 채널 이벤트가 이 신호와 매치될 때
        # "몇 분 전 이 판정 기록"으로 클릭 이동할 수 있다(mcp-server domain/entities.py의
        # ChannelSignal.source_ref 상단 주석 참고).
        call_id = str(uuid.uuid4())

        # N-03: mcp-server(LLM 포함)에는 마스킹된 텍스트만 보낸다 — domain/pii_masking.py
        # 상단 주석 참고("WHY 마스킹을 mcp-server 호출 전에 적용하는가").
        masked_transcript = mask_pii(transcript)
        raw = self._call_analysis_port.analyze(masked_transcript, channel)
        # F-06 대시보드(2026-09-02): 상관관계 가산 "전" 원점수를 보존한다 — 대시보드가
        # 위험도 배지(가산 후)와 판정 근거 안 점수(가산 전)를 각각 정확히 보여주려면
        # 둘 다 필요하다(item 3, "95 → 100" 표기).
        base_risk_score = raw["risk_score"]
        correlation_matches: list[CorrelationMatchSummary] = []

        # 우선순위 2(크로스채널 상관관계 탐지): mask_pii()가 지우기 "전" 원문에서
        # 엔티티(전화번호/계좌번호/URL)를 추출한다 — mcp-server가 받는 masked_transcript
        # 에는 이미 이 값들이 태그로 치환돼 있어서 추출할 게 없다(entity_extraction.py
        # 상단 주석 참고). entities만 mcp-server로 보내고 원문 자체는 안 보낸다.
        if self._correlation_port is not None:
            entities = extract_entities(transcript)
            if entities:
                correlation = self._correlation_port.correlate(
                    channel=channel,
                    entities=[{"entity_type": e.entity_type, "value": e.value} for e in entities],
                    occurred_at=(occurred_at or datetime.now(timezone.utc)).isoformat(),
                    context_excerpt=masked_transcript[:200],
                    current_risk_score=raw["risk_score"],
                    source_ref=call_id,
                )
                # 크로스채널 매치가 없어도 flagged_urls(Google Safe Browsing)만으로
                # 가산점이 붙을 수 있다 — matches만 보면 그 경우를 놓친다(mcp-server의
                # CallAnalysisService.execute()에서 발견한 것과 동일한 종류의 버그,
                # 여기 apps/api의 별도 상관관계 결합 경로에도 있었다).
                matches = correlation.get("matches", [])
                flagged_urls = correlation.get("flagged_urls", [])
                if matches or flagged_urls:
                    raw = _merge_correlation_into_raw(raw, correlation)
                    # F-06 대시보드(item 2, 2026-09-02): reasons는 matches 근거가 먼저,
                    # flagged_urls 근거가 뒤에 이어붙는 순서를 지킨다(mcp-server
                    # MultichannelCorrelationService.correlate 참고) — 그 순서로
                    # flagged_urls 쪽 근거 문장을 잘라낸다. flagged_urls는 "다른 채널
                    # 기록"이 아니라 외부 위협 인텔리전스 판정이라 source_call_id가 없다.
                    all_reasons = correlation.get("reasons", [])
                    url_reasons = all_reasons[len(matches):]
                    correlation_matches = [
                        CorrelationMatchSummary(reason=m.get("reason", ""), source_call_id=m.get("source_ref"))
                        for m in matches
                    ] + [CorrelationMatchSummary(reason=reason, source_call_id=None) for reason in url_reasons]

        result = CallAnalysisResult(
            call_id=call_id,
            raw_transcript=transcript,
            masked_transcript=masked_transcript,
            risk_score=raw["risk_score"],
            risk_level=RiskLevel(raw["risk_level"]),
            detected_patterns=[
                DetectedPatternSummary(
                    category=p["category"],
                    category_label=p["category_label"],
                    matched_keywords=p["matched_keywords"],
                )
                for p in raw["detected_patterns"]
            ],
            explanation_summary=raw["explanation_summary"],
            explanation=raw["explanation"],
            analyzed_at=datetime.now(timezone.utc),
            # .get(): 구버전 mcp-server(이 필드 추가 전)와의 호환을 위해 방어적으로 처리
            similar_cases=[
                SimilarCaseSummary(
                    case_id=c["case_id"],
                    title=c["title"],
                    category=c["category"],
                    summary=c["summary"],
                    source_note=c["source_note"],
                    similarity=c["similarity"],
                )
                for c in raw.get("similar_cases", [])
            ],
            channel=channel,
            base_risk_score=base_risk_score,
            correlation_matches=correlation_matches,
        )
        self._call_log_port.add(result)
        return result


class TranscribeAndAnalyzeCallService:
    """F-05 유스케이스: 모바일 앱이 올린 오디오 청크를 stt-worker로 텍스트 변환한 뒤,
    AnalyzeCallService에 그대로 위임한다. 판정 로직을 다시 구현하지 않고 기존
    text-경로(AnalyzeCallService)를 재사용해, 텍스트 입력과 오디오 입력이 항상 같은
    판정 결과를 내도록 한다.
    """

    def __init__(self, transcription_port: TranscriptionPort, analyze_call_service: AnalyzeCallService):
        self._transcription_port = transcription_port
        self._analyze_call_service = analyze_call_service

    async def execute(self, audio_bytes: bytes) -> CallAnalysisResult:
        transcript = self._transcription_port.transcribe(audio_bytes)
        return await self._analyze_call_service.execute(transcript)


class CallLogQueryService:
    """F-06 관제 대시보드 조회 유스케이스: 최근 탐지 현황과 통계를 제공한다."""

    def __init__(self, call_log_port: CallLogPort):
        self._call_log_port = call_log_port

    def list_recent(self, limit: int = 20) -> list[CallAnalysisResult]:
        return self._call_log_port.list_recent(limit)

    def stats_summary(self) -> StatsSummary:
        return self._call_log_port.stats_summary()


class ReportSubmissionService:
    """F-07 유스케이스: 신고 접수(mock)를 mcp-server(submit_report)에 위임한다.

    실제 접수 로직(채널 분기, report_id 발급 등)은 mcp-server가 갖고 있고, 여기는
    AnalyzeCallService와 동일하게 순수 오케스트레이션만 한다. mcp-server의 신고
    기록과 apps/api의 CallAnalysisResult 감사로그는 아직 연결되어 있지 않다
    (mcp-server ReportSubmissionService 상단 TODO 참고) — 지금은 call_id 없이
    case_summary/risk_level만 전달한다.
    """

    def __init__(self, report_port: ReportPort):
        self._report_port = report_port

    def execute(self, case_summary: str, risk_level: str) -> dict:
        return self._report_port.submit(case_summary, risk_level)


class DeepvoiceDetectionService:
    """F-03 유스케이스: 통화 음성이 AI 합성 음성인지 판별한다.

    실제 판별 알고리즘(음향 특징 휴리스틱, 나중에는 학습된 모델)은 infrastructure의
    어댑터가 구현하고, 여기서는 domain/ports.py의 DeepvoiceDetectionPort로만 의존한다
    (rag-worker의 SimilarCaseSearchService와 동일한 패턴).

    TODO (고도화 순서 제안):
      1. (완료) 음향 특징(피치 안정성/스펙트럼 평탄도/묵음 규칙성) 기반 휴리스틱 v1
         (infrastructure/adapters/deepvoice_adapter.py 참고)
      2. (완료) 실제 음성 샘플(합성 음성 vs 육성)로 임계값 보정
      3. (완료) 검증된 오픈소스 스푸핑 탐지 모델로 교체 —
         infrastructure/adapters/wav2vec2_deepvoice_adapter.py(v2, 기본값).
         DeepvoiceDetectionPort는 그대로 유지됨(N-06, 0줄 변경)
      4. (완료) N-05(5초 이내) SLA 계측 — main.py의 _record_analysis_metrics
    """

    def __init__(self, detection_port: DeepvoiceDetectionPort):
        self._detection_port = detection_port

    async def execute(self, audio_bytes: bytes) -> DeepvoiceVerdict:
        return self._detection_port.analyze(audio_bytes)
