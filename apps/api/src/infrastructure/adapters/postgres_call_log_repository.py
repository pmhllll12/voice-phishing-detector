# N-01 감사증적을 postgres에 영구 저장한다. domain/ports.py의 CallLogPort를 구현한다.
#
# append-only는 애플리케이션 코드가 아니라 DB 트리거(infra/db/init.sql의
# reject_audit_log_mutation)로 강제한다 — 이 클래스는 UPDATE/DELETE 메서드 자체를
# 갖고 있지 않지만, 설령 나중에 실수로 추가되더라도 DB가 거부한다.
#
# 연결은 첫 실제 호출 시점에 1회만 맺고(autocommit) 재사용한다 — __init__에서 바로
# 연결하지 않는 이유: main.py가 모듈 스코프에서 이 클래스를 인스턴스화하는데,
# __init__에서 연결하면 pytest가 src.main을 import하기만 해도 postgres가 떠 있어야
# 하는 문제가 생긴다 (apps/rag-worker·apps/stt-worker의 readiness.py를 분리한 것과
# 동일한 이유 — 커밋 d17ba24 참고). 연결은 uvicorn 기본 실행 방식(단일 워커/이벤트루프)
# 기준으로 별도 커넥션 풀 없이도 요청이 직렬화되어 처리된다. 연결이 끊기면(postgres
# 재시작 등) 재연결 로직 없이 다음 호출에서 예외가 난다 — 지금 규모에서는 재연결/풀링까지
# 갖추는 것이 과설계라고 판단해 TODO로만 남긴다.

import psycopg
from psycopg.types.json import Jsonb

from src.domain.entities import (
    CallAnalysisResult,
    DetectedPatternSummary,
    RiskLevel,
    SimilarCaseSummary,
    StatsSummary,
    compute_stats_summary,
)

_SELECT_COLUMNS = (
    "call_id, raw_transcript, risk_score, risk_level, detected_patterns, "
    "explanation_summary, explanation, similar_cases, analyzed_at"
)


class PostgresCallLogRepository:
    # TODO: 커넥션이 끊기면(postgres 재시작 등) 재연결하지 않는다 — 위 모듈 주석 참고.
    def __init__(self, dsn: str, options: str | None = None):
        self._dsn = dsn
        self._options = options
        self._conn: psycopg.Connection | None = None

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None:
            self._conn = psycopg.connect(self._dsn, autocommit=True, options=self._options)
        return self._conn

    def ping(self) -> None:
        """/ready 체크 전용 — 연결이 살아있는지만 확인한다. 예외를 그대로 전파한다."""
        self._get_conn().execute("SELECT 1")

    def add(self, result: CallAnalysisResult) -> None:
        self._get_conn().execute(
            f"""
            INSERT INTO call_analysis_results
                ({_SELECT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.call_id,
                result.raw_transcript,
                result.risk_score,
                result.risk_level.value,
                Jsonb(
                    [
                        {"category": p.category, "category_label": p.category_label, "matched_keywords": p.matched_keywords}
                        for p in result.detected_patterns
                    ]
                ),
                result.explanation_summary,
                result.explanation,
                Jsonb(
                    [
                        {
                            "case_id": c.case_id,
                            "title": c.title,
                            "category": c.category,
                            "summary": c.summary,
                            "source_note": c.source_note,
                            "similarity": c.similarity,
                        }
                        for c in result.similar_cases
                    ]
                ),
                result.analyzed_at,
            ),
        )

    def list_recent(self, limit: int) -> list[CallAnalysisResult]:
        rows = self._get_conn().execute(
            f"SELECT {_SELECT_COLUMNS} FROM call_analysis_results ORDER BY analyzed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._row_to_result(row) for row in rows]

    def stats_summary(self) -> StatsSummary:
        rows = self._get_conn().execute(f"SELECT {_SELECT_COLUMNS} FROM call_analysis_results").fetchall()
        return compute_stats_summary([self._row_to_result(row) for row in rows])

    @staticmethod
    def _row_to_result(row: tuple) -> CallAnalysisResult:
        (
            call_id,
            raw_transcript,
            risk_score,
            risk_level,
            detected_patterns,
            explanation_summary,
            explanation,
            similar_cases,
            analyzed_at,
        ) = row
        return CallAnalysisResult(
            call_id=str(call_id),
            raw_transcript=raw_transcript,
            risk_score=risk_score,
            risk_level=RiskLevel(risk_level),
            detected_patterns=[DetectedPatternSummary(**p) for p in detected_patterns],
            explanation_summary=explanation_summary,
            explanation=explanation,
            analyzed_at=analyzed_at,
            similar_cases=[SimilarCaseSummary(**c) for c in similar_cases],
        )
