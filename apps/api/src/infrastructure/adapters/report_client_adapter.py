# F-07 신고 접수(mock)를 mcp-server(/api/v1/reports)에 HTTP로 위임하는 어댑터.
# domain/ports.py의 ReportPort를 구현한다. mcp_client_adapter.py와 동일한 패턴.
#
# mcp-server가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/mcp-server && source .venv/bin/activate
#   uvicorn rest_server:app --app-dir src --port 8100

import httpx


class McpServerReportAdapter:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._base_url = base_url
        self._timeout = timeout

    def submit(self, case_summary: str, risk_level: str) -> dict:
        response = httpx.post(
            f"{self._base_url}/api/v1/reports",
            json={"case_summary": case_summary, "risk_level": risk_level},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()
