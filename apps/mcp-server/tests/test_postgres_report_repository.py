# PostgresReportRepository를 실제 로컬 postgres(docker vps-postgres, infra/db/init.sql
# 스키마)로 검증하는 통합 테스트. 격리 전략/스킵 조건은 apps/api의
# test_postgres_call_log_repository.py와 동일 — 그쪽 상단 주석 참고.

import datetime
import os
import pathlib
import uuid

import psycopg
import pytest

from domain.entities import ReportRecord, RiskLevel
from infrastructure.adapters.postgres_report_repository import PostgresReportRepository

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)
INIT_SQL = (pathlib.Path(__file__).resolve().parent.parent.parent.parent / "infra" / "db" / "init.sql").read_text(
    encoding="utf-8"
)

try:
    psycopg.connect(TEST_DSN, connect_timeout=2).close()
    _POSTGRES_AVAILABLE = True
except psycopg.OperationalError:
    _POSTGRES_AVAILABLE = False

pytestmark = pytest.mark.skipif(not _POSTGRES_AVAILABLE, reason="로컬 postgres(vps-postgres)가 떠 있지 않음")


@pytest.fixture
def repository():
    schema = f"test_{uuid.uuid4().hex[:8]}"
    setup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    setup_conn.execute(f"CREATE SCHEMA {schema}")
    setup_conn.execute(f"SET search_path TO {schema}")
    setup_conn.execute(INIT_SQL)
    setup_conn.close()

    repo = PostgresReportRepository(TEST_DSN, options=f"-c search_path={schema}")
    yield repo

    cleanup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    cleanup_conn.execute(f"DROP SCHEMA {schema} CASCADE")
    cleanup_conn.close()


def _make_record(**overrides) -> ReportRecord:
    defaults = dict(
        report_id=str(uuid.uuid4()),
        case_summary="검찰 사칭 통화, 계좌이체 요구",
        risk_level=RiskLevel.HIGH,
        channel="auto",
        status="submitted",
        submitted_at=datetime.datetime.now(datetime.timezone.utc),
    )
    defaults.update(overrides)
    return ReportRecord(**defaults)


def test_add_and_list_recent_round_trips_all_fields(repository):
    record = _make_record()

    repository.add(record)
    fetched = repository.list_recent(10)

    assert len(fetched) == 1
    got = fetched[0]
    assert got.report_id == record.report_id
    assert got.case_summary == record.case_summary
    assert got.risk_level == RiskLevel.HIGH
    assert got.channel == "auto"
    assert got.status == "submitted"


def test_list_recent_orders_most_recent_first_and_respects_limit(repository):
    older = _make_record(submitted_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    newer = _make_record(submitted_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc))
    repository.add(older)
    repository.add(newer)

    fetched = repository.list_recent(1)

    assert len(fetched) == 1
    assert fetched[0].report_id == newer.report_id


def test_append_only_trigger_rejects_update(repository):
    repository.add(_make_record())

    with pytest.raises(psycopg.errors.RaiseException, match="N-01"):
        repository._get_conn().execute("UPDATE report_records SET status = 'closed'")


def test_append_only_trigger_rejects_delete(repository):
    repository.add(_make_record())

    with pytest.raises(psycopg.errors.RaiseException, match="N-01"):
        repository._get_conn().execute("DELETE FROM report_records")


def test_ping_succeeds_when_reachable(repository):
    repository.ping()
