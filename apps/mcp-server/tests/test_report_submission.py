from application.services import ReportSubmissionService
from domain.entities import RiskLevel
from infrastructure.adapters.in_memory_report_repository import InMemoryReportRepository


def _service() -> ReportSubmissionService:
    return ReportSubmissionService(InMemoryReportRepository())


def test_high_risk_report_is_routed_to_auto_channel():
    service = _service()
    record = service.submit("검찰 사칭 통화, 계좌이체 요구", RiskLevel.HIGH)

    assert record.channel == "auto"
    assert record.status == "submitted"
    assert record.report_id  # uuid 문자열이 발급되어야 함


def test_non_high_risk_report_is_routed_to_manual_channel():
    service = _service()

    assert service.submit("경미한 의심 사례", RiskLevel.LOW).channel == "manual"
    assert service.submit("중간 위험 사례", RiskLevel.MEDIUM).channel == "manual"


def test_each_submission_gets_a_unique_report_id():
    service = _service()
    first = service.submit("사례 A", RiskLevel.HIGH)
    second = service.submit("사례 B", RiskLevel.HIGH)

    assert first.report_id != second.report_id


def test_submitted_reports_are_persisted_and_listed_most_recent_first():
    repository = InMemoryReportRepository()
    service = ReportSubmissionService(repository)

    service.submit("사례 A", RiskLevel.LOW)
    service.submit("사례 B", RiskLevel.HIGH)

    recent = repository.list_recent(limit=10)
    assert [r.case_summary for r in recent] == ["사례 B", "사례 A"]
