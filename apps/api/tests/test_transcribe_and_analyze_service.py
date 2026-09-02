# F-05 유스케이스(TranscribeAndAnalyzeCallService) 검증. 실제 stt-worker/mcp-server
# HTTP 호출 없이, 포트를 페이크로 대체해 "오디오 -> 텍스트 변환 -> 기존 텍스트 판정
# 경로 재사용 -> 감사증적 적재"가 올바른 순서로 이어지는지만 확인한다. pytest-asyncio가
# 없으므로(requirements-dev.txt 참고) asyncio.run으로 async execute()를 직접 구동한다.

import asyncio

from src.application.services import AnalyzeCallService, TranscribeAndAnalyzeCallService
from src.infrastructure.adapters.in_memory_call_log import InMemoryCallLogRepository


class _FakeTranscriptionPort:
    def __init__(self, text: str):
        self._text = text
        self.received_audio_bytes: bytes | None = None

    def transcribe(self, audio_bytes: bytes) -> str:
        self.received_audio_bytes = audio_bytes
        return self._text


class _FakeCallAnalysisPort:
    def __init__(self):
        self.received_transcript: str | None = None

    def analyze(self, transcript: str, channel: str = "call") -> dict:
        self.received_transcript = transcript
        return {
            "risk_score": 80,
            "risk_level": "high",
            "detected_patterns": [
                {"category": "impersonation", "category_label": "기관사칭", "matched_keywords": ["검찰청"]}
            ],
            "explanation_summary": "요약",
            "explanation": "근거",
        }


def _build_service(transcription_port, call_analysis_port, call_log_repository):
    analyze_call_service = AnalyzeCallService(call_analysis_port, call_log_repository)
    return TranscribeAndAnalyzeCallService(transcription_port, analyze_call_service)


def test_transcribed_text_is_forwarded_to_call_analysis():
    transcription_port = _FakeTranscriptionPort("검찰청인데 계좌 비밀번호 불러주세요")
    call_analysis_port = _FakeCallAnalysisPort()
    service = _build_service(transcription_port, call_analysis_port, InMemoryCallLogRepository())

    result = asyncio.run(service.execute(b"fake-wav-bytes"))

    assert transcription_port.received_audio_bytes == b"fake-wav-bytes"
    assert call_analysis_port.received_transcript == "검찰청인데 계좌 비밀번호 불러주세요"
    assert result.raw_transcript == "검찰청인데 계좌 비밀번호 불러주세요"
    assert result.risk_level.value == "high"


def test_result_is_persisted_to_call_log_like_the_text_path():
    call_log_repository = InMemoryCallLogRepository()
    service = _build_service(_FakeTranscriptionPort("텍스트"), _FakeCallAnalysisPort(), call_log_repository)

    asyncio.run(service.execute(b"audio-bytes"))

    assert len(call_log_repository.list_recent(10)) == 1
