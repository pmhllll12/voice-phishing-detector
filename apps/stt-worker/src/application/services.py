# application 계층: 모바일 실시간 감지 파이프라인의 STT 유스케이스.
# 실제 변환은 infrastructure의 어댑터가 구현하고, 여기서는
# domain/ports.py의 SpeechToTextPort 인터페이스로만 의존한다.

from src.domain.entities import TranscriptionResult
from src.domain.ports import SpeechToTextPort


class TranscribeAudioService:
    """모바일 앱이 5~10초 단위로 잘라 보내는 오디오 청크를 텍스트로 변환한다.

    이 결과 텍스트를 apps/api가 이어서 mcp-server(F-01/F-02)에 넘겨 위험도를
    판정한다 — 즉 이 서비스는 파이프라인의 "오디오 -> 텍스트" 구간만 담당하고,
    보이스피싱 판정 로직은 전혀 알지 못한다(단일 책임 유지).
    """

    def __init__(self, stt_port: SpeechToTextPort):
        self._stt_port = stt_port

    def execute(self, audio_bytes: bytes) -> TranscriptionResult:
        return self._stt_port.transcribe(audio_bytes)
