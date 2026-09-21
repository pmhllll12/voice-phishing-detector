# PostgresCallLogRepository를 실제 로컬 postgres(docker vps-postgres, infra/db/init.sql
# 스키마)로 검증하는 통합 테스트. append-only 트리거(UPDATE/DELETE 거부) 검증도 여기서
# 함께 한다 — 애플리케이션 코드에는 update/delete 메서드 자체가 없어서 단위 테스트로는
# "DB가 실제로 거부하는지"를 확인할 수 없기 때문이다.
#
# 격리 전략: 매 테스트마다 고유한 postgres 스키마를 만들고 search_path로 그 스키마만
# 보게 한 뒤(infra/db/init.sql을 그 스키마 안에 그대로 적용), 테스트가 끝나면 스키마를
# DROP한다. append-only 트리거는 row-level DELETE만 막고 DROP SCHEMA(DDL)는 막지 않으므로
# 이 방식으로 정리할 수 있다.
#
# TEST_DATABASE_URL이 설정되어 있지 않으면 로컬 기본값(vps-postgres 컨테이너)을 쓰고,
# 그마저 접속이 안 되면 모듈 전체를 skip한다 — postgres 없이 돌아가는 나머지 테스트
# 스위트(단위 테스트)는 이 파일과 무관하게 항상 통과해야 한다(src/main.py 상단 주석의
# "src.main을 import하기만 해도 postgres가 필요해지는 문제" 참고).

import datetime
import os
import pathlib
import uuid

import psycopg
import pytest

from src.domain.entities import CallAnalysisResult, DetectedPatternSummary, RiskLevel, SimilarCaseSummary
from src.infrastructure.adapters.postgres_call_log_repository import PostgresCallLogRepository

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
    # public도 search_path에 넣어야 한다 — init.sql이 fraud_cases(F-04, rag-worker
    # 소관이지만 이 파일 스키마에 함께 적용됨)에서 쓰는 vector 타입이 public에 있다.
    setup_conn.execute(f"SET search_path TO {schema}, public")
    setup_conn.execute(INIT_SQL)
    setup_conn.close()

    repo = PostgresCallLogRepository(TEST_DSN, options=f"-c search_path={schema}")
    yield repo

    cleanup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    cleanup_conn.execute(f"DROP SCHEMA {schema} CASCADE")
    cleanup_conn.close()


def _make_result(call_id: str | None = None, **overrides) -> CallAnalysisResult:
    defaults = dict(
        call_id=call_id or str(uuid.uuid4()),
        raw_transcript="검찰청인데 안전계좌로 이체하세요",
        masked_transcript="검찰청인데 안전계좌로 이체하세요",
        risk_score=95,
        risk_level=RiskLevel.HIGH,
        detected_patterns=[
            DetectedPatternSummary(category="authority_impersonation", category_label="기관사칭", matched_keywords=["검찰청"])
        ],
        explanation_summary="고위험 등급 (위험도 95점)",
        explanation="고위험 등급 (위험도 95점) — ...",
        analyzed_at=datetime.datetime.now(datetime.timezone.utc),
        similar_cases=[
            SimilarCaseSummary(
                case_id="FC-001",
                title="검찰 사칭 - 계좌 범죄 연루 통보형",
                category="기관사칭형",
                summary="...",
                source_note="...",
                similarity=0.8,
            )
        ],
    )
    defaults.update(overrides)
    return CallAnalysisResult(**defaults)


def test_add_and_list_recent_round_trips_all_fields(repository):
    result = _make_result()

    repository.add(result)
    fetched = repository.list_recent(10)

    assert len(fetched) == 1
    got = fetched[0]
    assert got.call_id == result.call_id
    assert got.raw_transcript == result.raw_transcript
    assert got.masked_transcript == result.masked_transcript
    assert got.risk_score == result.risk_score
    assert got.risk_level == RiskLevel.HIGH
    assert got.detected_patterns == result.detected_patterns
    assert got.similar_cases == result.similar_cases


def test_list_recent_orders_most_recent_first_and_respects_limit(repository):
    older = _make_result(analyzed_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    newer = _make_result(analyzed_at=datetime.datetime(2026, 6, 1, tzinfo=datetime.timezone.utc))
    repository.add(older)
    repository.add(newer)

    fetched = repository.list_recent(1)

    assert len(fetched) == 1
    assert fetched[0].call_id == newer.call_id


def test_stats_summary_aggregates_across_records(repository):
    repository.add(_make_result(risk_score=95, risk_level=RiskLevel.HIGH))
    repository.add(
        _make_result(
            risk_score=0,
            risk_level=RiskLevel.LOW,
            detected_patterns=[],
            similar_cases=[],
        )
    )

    stats = repository.stats_summary()

    assert stats.total_analyzed == 2
    assert stats.risk_level_counts["high"] == 1
    assert stats.risk_level_counts["low"] == 1
    assert stats.category_counts[0].category == "authority_impersonation"


def test_append_only_trigger_rejects_update(repository):
    result = _make_result()
    repository.add(result)

    with pytest.raises(psycopg.errors.RaiseException, match="N-01"):
        repository._get_conn().execute("UPDATE call_analysis_results SET risk_score = 0")


def test_append_only_trigger_rejects_delete(repository):
    result = _make_result()
    repository.add(result)

    with pytest.raises(psycopg.errors.RaiseException, match="N-01"):
        repository._get_conn().execute("DELETE FROM call_analysis_results")


def test_ping_succeeds_when_reachable(repository):
    repository.ping()  # 예외 없이 통과하면 성공


def test_reconnects_and_succeeds_after_connection_is_closed(repository):
    """postgres 단일 장애점 완화 실측(2026-09-01) 회귀 가드 — 실제로 로컬 postgres를
    재기동시켜보고 재현했던 문제(연결이 끊긴 채로 남아 `/ready`가 계속 실패)를 여기서
    재현한다. `.close()`로 클라이언트 쪽에서 연결을 끊어 "postgres 재시작으로 서버가
    연결을 끊었다"를 흉내내고, 다음 호출이 예외 없이 성공하며 실제로 새 연결 객체로
    교체됐는지 확인한다."""
    repository.ping()  # 최초 연결을 맺어둔다
    stale_conn = repository._conn
    stale_conn.close()

    repository.ping()  # 예외 없이 통과해야 한다 — 내부적으로 재연결됨

    assert repository._conn is not stale_conn
    assert not repository._conn.closed


def test_write_survives_connection_drop_between_calls(repository):
    """ping뿐 아니라 실제 쓰기 경로(add)도 재연결 후 정상 동작해야 한다."""
    repository.add(_make_result())
    repository._conn.close()

    repository.add(_make_result())  # 재연결 후 재시도되어 성공해야 함

    assert len(repository.list_recent(10)) == 2


def test_legacy_row_without_masked_transcript_is_masked_on_read():
    """N-03 도입(2026-08-31) 전에 적재된 행은 masked_transcript가 NULL이다(컬럼을
    ALTER TABLE로 추가했고 기존 행을 backfill하지 않음, infra/db/init.sql 참고). 이런
    레거시 행도 읽을 때 그 자리에서 마스킹돼야 한다 — 그렇지 않으면 프런트엔드가 null을
    그대로 받아 깨지거나(과거 실제로 발생), 원문 PII가 그대로 노출된다."""
    schema = f"test_{uuid.uuid4().hex[:8]}"
    setup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    setup_conn.execute(f"CREATE SCHEMA {schema}")
    setup_conn.execute(f"SET search_path TO {schema}, public")
    setup_conn.execute(INIT_SQL)
    setup_conn.execute(
        """
        INSERT INTO call_analysis_results
            (call_id, raw_transcript, masked_transcript, risk_score, risk_level,
             detected_patterns, explanation_summary, explanation, similar_cases, analyzed_at)
        VALUES (%s, %s, NULL, %s, %s, '[]'::jsonb, %s, %s, '[]'::jsonb, %s)
        """,
        (
            str(uuid.uuid4()),
            "010-1234-5678로 전화드렸습니다",
            10,
            "low",
            "위험도 낮음",
            "특이사항 없음",
            datetime.datetime.now(datetime.timezone.utc),
        ),
    )

    repo = PostgresCallLogRepository(TEST_DSN, options=f"-c search_path={schema},public")
    fetched = repo.list_recent(1)

    setup_conn.execute(f"DROP SCHEMA {schema} CASCADE")
    setup_conn.close()

    assert fetched[0].masked_transcript == "[전화번호]로 전화드렸습니다"
