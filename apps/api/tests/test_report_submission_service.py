# F-07 유스케이스(ReportSubmissionService) 검증. 실제 mcp-server HTTP 호출 없이
# ReportPort를 페이크로 대체해 요청/응답이 그대로 통과하는지만 확인한다 — 채널 분기 등
# 실제 접수 로직은 mcp-server 쪽(test_report_submission.py)에서 이미 검증된다.

from src.application.services import ReportSubmissionService


class _FakeReportPort:
    def __init__(self, response: dict):
        self._response = response
        self.received: tuple[str, str] | None = None

    def submit(self, case_summary: str, risk_level: str) -> dict:
        self.received = (case_summary, risk_level)
        return self._response


def test_execute_forwards_case_summary_and_risk_level_to_port():
    port = _FakeReportPort({"report_id": "r-1", "status": "submitted", "channel": "auto"})
    service = ReportSubmissionService(port)

    result = service.execute("검찰 사칭 통화", "high")

    assert port.received == ("검찰 사칭 통화", "high")
    assert result == {"report_id": "r-1", "status": "submitted", "channel": "auto"}
