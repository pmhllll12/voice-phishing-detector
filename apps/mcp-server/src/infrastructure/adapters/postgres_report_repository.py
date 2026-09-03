# N-01 감사증적을 postgres에 영구 저장한다. domain/ports.py의 ReportRepositoryPort를
# 구현한다. apps/api의 PostgresCallLogRepository와 동일한 패턴/한계를 따른다 — 연결은
# __init__이 아니라 첫 실제 호출 시점에 맺는다(모듈 스코프에서 인스턴스화하는
# server.py/rest_server.py를 pytest가 import하기만 해도 postgres가 필요해지는 문제를
# 피하기 위함). 재연결(postgres 단일 장애점 완화, 2026-09-01)도 apps/api와 동일한
# 이유/방식 — 그쪽 상단 주석 참고.
#
# append-only는 DB 트리거(infra/db/init.sql의 reject_audit_log_mutation)로 강제된다.

import psycopg

from domain.entities import ReportRecord, RiskLevel

_SELECT_COLUMNS = "report_id, case_summary, risk_level, channel, status, submitted_at"


class PostgresReportRepository:
    def __init__(self, dsn: str, options: str | None = None):
        self._dsn = dsn
        self._options = options
        self._conn: psycopg.Connection | None = None

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._dsn, autocommit=True, options=self._options)

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _execute(self, query: str, params: tuple = ()):
        """OperationalError(연결 끊김)면 재연결 후 한 번만 재시도한다."""
        try:
            return self._get_conn().execute(query, params)
        except psycopg.OperationalError:
            self._conn = self._connect()
            return self._conn.execute(query, params)

    def ping(self) -> None:
        """/ready 체크 전용 — 연결이 살아있는지만 확인한다. 예외를 그대로 전파한다."""
        self._execute("SELECT 1")

    def add(self, record: ReportRecord) -> None:
        self._execute(
            f"INSERT INTO report_records ({_SELECT_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                record.report_id,
                record.case_summary,
                record.risk_level.value,
                record.channel,
                record.status,
                record.submitted_at,
            ),
        )

    def list_recent(self, limit: int) -> list[ReportRecord]:
        rows = self._execute(
            f"SELECT {_SELECT_COLUMNS} FROM report_records ORDER BY submitted_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: tuple) -> ReportRecord:
        report_id, case_summary, risk_level, channel, status, submitted_at = row
        return ReportRecord(
            report_id=str(report_id),
            case_summary=case_summary,
            risk_level=RiskLevel(risk_level),
            channel=channel,
            status=status,
            submitted_at=submitted_at,
        )
