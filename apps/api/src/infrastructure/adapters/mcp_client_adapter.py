# F-01/F-02/F-05 판정을 mcp-server(rest_server.py)에 HTTP로 위임하는 어댑터.
# domain/ports.py의 CallAnalysisPort를 구현한다.
#
# mcp-server가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/mcp-server && source .venv/bin/activate
#   uvicorn rest_server:app --app-dir src --port 8100

import httpx


class McpServerCallAnalysisAdapter:
    def __init__(self, base_url: str, timeout: float = 10.0):
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
