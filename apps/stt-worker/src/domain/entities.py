# domain 계층: 외부 의존성 없는 순수 모델.

from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptionResult:
    """모바일 앱이 보낸 오디오 청크 1건을 텍스트로 변환한 결과.

    이 결과의 text는 apps/api가 그대로 mcp-server(F-01/F-02 위험도 판정)에 넘긴다 —
    STT는 판정 로직을 전혀 모르고, 오직 "오디오 -> 텍스트" 변환만 책임진다.
    """

    text: str
    language: str
    duration_seconds: float
