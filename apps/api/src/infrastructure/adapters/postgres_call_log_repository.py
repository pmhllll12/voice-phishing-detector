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
# 기준으로 별도 커넥션 풀 없이도 요청이 직렬화되어 처리된다.
#
# 재연결(postgres 단일 장애점 완화, 2026-09-01): docker-compose.yaml의
# `restart: unless-stopped`로 postgres 프로세스 자체는 크래시 후 자동으로 다시 뜨지만,
# 이 클래스가 들고 있던 psycopg 연결 객체는 여전히 끊긴 채로 남는다 — 실제로 로컬에서
# postgres 컨테이너를 재기동시켜보고 `/ready`가 "OperationalError: the connection is
# closed"로 계속 실패하는 걸 확인했다(api를 수동 재시작해야만 복구됐음). 그래서 쿼리가
# OperationalError로 실패하면 연결을 버리고 한 번 재연결해 재시도한다 — 재시도까지
# 실패하면(진짜 다운) 예외를 그대로 올린다. 커넥션 풀링(예: psycopg_pool)까지는 지금
# 규모(단일 워커, 요청 직렬화)에서 과설계라고 판단해 도입하지 않았다.

import psycopg
from psycopg.types.json import Jsonb

from dataclasses import dataclass

from src.domain.entities import (
    CallAnalysisResult,
    CorrelationMatchSummary,
    DetectedPatternSummary,
    RiskLevel,
    SimilarCaseSummary,
    StatsSummary,
    compute_stats_summary,
)
from src.domain.pii_masking import mask_pii

_SELECT_COLUMNS = (
    "call_id, raw_transcript, masked_transcript, risk_score, risk_level, detected_patterns, "
    "explanation_summary, explanation, similar_cases, analyzed_at, channel, "
    "base_risk_score, correlation_matches"
)


@dataclass
class _StatsRow:
    """domain.entities.StatsSourceRecord를 만족하는 경량 레코드 — stats_summary()가
    필요한 필드 2개만 담는다(위 클래스 상단 주석 참고)."""

    risk_level: RiskLevel
    detected_patterns: list[DetectedPatternSummary]


class PostgresCallLogRepository:
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
        """OperationalError(연결 끊김)면 재연결 후 한 번만 재시도한다 — 클래스 상단
        주석 "재연결" 절 참고."""
        try:
            return self._get_conn().execute(query, params)
        except psycopg.OperationalError:
            self._conn = self._connect()
            return self._conn.execute(query, params)

    def ping(self) -> None:
        """/ready 체크 전용 — 연결이 살아있는지만 확인한다. 예외를 그대로 전파한다."""
        self._execute("SELECT 1")

    def add(self, result: CallAnalysisResult) -> None:
        self._execute(
            f"""
            INSERT INTO call_analysis_results
                ({_SELECT_COLUMNS})
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                result.call_id,
                result.raw_transcript,
                result.masked_transcript,
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
                result.channel,
                result.base_risk_score,
                Jsonb(
                    [
                        {"reason": m.reason, "source_call_id": m.source_call_id}
                        for m in result.correlation_matches
                    ]
                ),
            ),
        )

    def list_recent(self, limit: int) -> list[CallAnalysisResult]:
        rows = self._execute(
            f"SELECT {_SELECT_COLUMNS} FROM call_analysis_results ORDER BY analyzed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._row_to_result(row) for row in rows]

    def stats_summary(self) -> StatsSummary:
        # 코드 리뷰(2026-09-02) 대응: compute_stats_summary는 risk_level/detected_patterns
        # 두 필드만 쓰는데, 예전엔 _SELECT_COLUMNS 전체(raw_transcript/explanation/
        # similar_cases/correlation_matches 등)를 가져와 매핑한 뒤 대부분 버렸다 — 대시보드가
        # 10초마다 폴링하므로 데이터가 커질수록 불필요한 역직렬화 비용이 누적된다. 필요한
        # 컬럼 2개만 SELECT하고, 그 두 필드만 채운 경량 레코드를 domain의
        # StatsSourceRecord Protocol(entities.py 참고)로 넘긴다.
        rows = self._execute("SELECT risk_level, detected_patterns FROM call_analysis_results").fetchall()
        return compute_stats_summary(
            [
                _StatsRow(RiskLevel(risk_level), [DetectedPatternSummary(**p) for p in patterns])
                for risk_level, patterns in rows
            ]
        )

    @staticmethod
    def _row_to_result(row: tuple) -> CallAnalysisResult:
        (
            call_id,
            raw_transcript,
            masked_transcript,
            risk_score,
            risk_level,
            detected_patterns,
            explanation_summary,
            explanation,
            similar_cases,
            analyzed_at,
            channel,
            base_risk_score,
            correlation_matches,
        ) = row
        # N-03 도입(2026-08-31) 이전에 적재된 행은 masked_transcript 컬럼이 NULL이다
        # (infra/db/init.sql의 ALTER TABLE ADD COLUMN 참고 — 기존 행을 backfill하지
        # 않음). 그런 레거시 행을 읽을 때는 그 자리에서 마스킹해 채워준다 — 그래야
        # 오래된 감사증적을 조회해도 원문이 그대로 노출되는 일이 없다.
        if masked_transcript is None:
            masked_transcript = mask_pii(raw_transcript)
        # F-06 대시보드(2026-09-02): base_risk_score 도입 이전 행은 NULL이다 — 상관관계
        # 가산이 없었던 것과 구분할 수 없지만(원 데이터 손실), risk_score로 대체해두면
        # UI가 최소한 "가산 없음"으로 안전하게 표시한다(95→100 배지를 안 그림).
        if base_risk_score is None:
            base_risk_score = risk_score
        return CallAnalysisResult(
            call_id=str(call_id),
            raw_transcript=raw_transcript,
            masked_transcript=masked_transcript,
            risk_score=risk_score,
            risk_level=RiskLevel(risk_level),
            detected_patterns=[DetectedPatternSummary(**p) for p in detected_patterns],
            explanation_summary=explanation_summary,
            explanation=explanation,
            analyzed_at=analyzed_at,
            similar_cases=[SimilarCaseSummary(**c) for c in similar_cases],
            channel=channel,
            base_risk_score=base_risk_score,
            correlation_matches=[CorrelationMatchSummary(**m) for m in correlation_matches],
        )
