# F-01/F-02/F-05 판정을 mcp-server(rest_server.py)에 HTTP로 위임하는 어댑터.
# domain/ports.py의 CallAnalysisPort를 구현한다.
#
# mcp-server가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/mcp-server && source .venv/bin/activate
#   uvicorn rest_server:app --app-dir src --port 8100

import httpx


class McpServerCallAnalysisAdapter:
    # 30초: Ollama가 유휴 상태에서 모델을 언로드한 뒤 첫 요청이 오면 콜드 스타트
    # 로딩(수 초~10초 이상)이 걸릴 수 있어, mcp-server의 LLM 호출 타임아웃(20초,
    # ollama_call_analysis_adapter.py)보다 여유 있게 잡았다.
    def __init__(self, base_url: str, timeout: float = 30.0):
        self._base_url = base_url
        self._timeout = timeout

    def analyze(self, transcript: str) -> dict:
        response = httpx.post(
            f"{self._base_url}/api/v1/analyze",
            json={"transcript": transcript},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()
