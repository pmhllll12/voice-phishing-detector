# F-05 모바일 실시간 감지: 오디오 청크를 stt-worker(/api/v1/transcribe)에 넘겨 텍스트로
# 변환하는 어댑터. domain/ports.py의 TranscriptionPort를 구현한다.
#
# stt-worker가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/stt-worker && source .venv/bin/activate
#   uvicorn src.main:app --port 8300

import httpx


class SttWorkerTranscriptionAdapter:
    # 30초: mcp_client_adapter.py와 동일한 근거로, faster-whisper 모델이 유휴 상태에서
    # 언로드된 뒤 첫 요청에서 콜드 스타트가 걸릴 수 있는 상황에 여유를 둔다.
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url
        self._timeout = timeout

    def transcribe(self, audio_bytes: bytes) -> str:
        response = httpx.post(
            f"{self._base_url}/api/v1/transcribe",
            files={"audio": ("chunk.wav", audio_bytes)},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()["text"]
