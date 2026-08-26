# domain 계층의 포트(인터페이스). "어떻게 음성을 텍스트로 바꾸는가"의 구체 구현은
# infrastructure에 맡기고, application은 이 인터페이스에만 의존한다 — 나중에
# faster-whisper에서 다른 STT 엔진으로 바꿔도 application/main.py는 그대로 유지된다
# (apps/rag-worker의 FraudCaseSearchPort, apps/mcp-server의 CallAnalysisPort와 동일한 목적).

from typing import Protocol

from .entities import TranscriptionResult


class SpeechToTextPort(Protocol):
    def transcribe(self, audio_bytes: bytes) -> TranscriptionResult: ...
