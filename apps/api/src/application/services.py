# application 계층: 유스케이스(비즈니스 프로세스)를 조합하는 곳.
# domain의 모델을 사용하되, 실제 DB/외부 API 호출은 infrastructure의 포트(인터페이스)를
# 통해서만 위임한다 — 그래야 이 계층을 테스트할 때 진짜 DB 없이도 테스트할 수 있다.

import uuid
from datetime import datetime, timezone

from src.domain.deepvoice import DeepvoiceVerdict
from src.domain.entities import (
    CallAnalysisResult,
    DetectedPatternSummary,
    RiskLevel,
    SimilarCaseSummary,
    StatsSummary,
)
from src.domain.pii_masking import mask_pii
from src.domain.ports import (
    CallAnalysisPort,
    CallLogPort,
    DeepvoiceDetectionPort,
    ReportPort,
    TranscriptionPort,
)


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

    def __init__(self, call_analysis_port: CallAnalysisPort, call_log_port: CallLogPort):
        self._call_analysis_port = call_analysis_port
        self._call_log_port = call_log_port

    async def execute(self, transcript: str) -> CallAnalysisResult:
        # N-03: mcp-server(LLM 포함)에는 마스킹된 텍스트만 보낸다 — domain/pii_masking.py
        # 상단 주석 참고("WHY 마스킹을 mcp-server 호출 전에 적용하는가").
        masked_transcript = mask_pii(transcript)
        raw = self._call_analysis_port.analyze(masked_transcript)

        result = CallAnalysisResult(
            call_id=str(uuid.uuid4()),
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
