# PgvectorSimilarityAdapter를 실제 로컬 postgres(docker vps-postgres, infra/db/init.sql
# 스키마)로 검증하는 통합 테스트. apps/api의 test_postgres_call_log_repository.py와
# 동일한 격리 전략(테스트마다 고유 스키마를 만들고 끝나면 DROP)을 쓰되, pgvector의
# vector 타입은 CREATE EXTENSION 시점에 public 스키마에 만들어지므로 격리 스키마의
# search_path에 public도 함께 넣어야 타입이 resolve된다.
#
# 코퍼스는 fraud_cases.json 실 데이터를 그대로 쓰고, 임베딩은 어댑터가 이미 로드한
# 모델(adapter._model)로 계산해 seed한다 — 모델을 두 번 로드하지 않기 위함이다.
# 이 테스트는 임베딩 모델 로딩까지 포함하므로 무겁다(로컬에서 실측 약 20초, HF Hub
# 조회 포함) — TEST_DATABASE_URL이 없거나 접속이 안 되면 모듈 전체를 skip한다.

import os
import pathlib
import uuid

import psycopg
import pytest
from pgvector.psycopg import register_vector

from src.infrastructure.adapters.pgvector_similarity_adapter import PgvectorSimilarityAdapter
from src.infrastructure.data_loader import load_fraud_cases

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


@pytest.fixture(scope="module")
def seeded_adapter():
    schema = f"test_{uuid.uuid4().hex[:8]}"
    setup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    setup_conn.execute(f"CREATE SCHEMA {schema}")
    setup_conn.execute(f"SET search_path TO {schema}, public")
    setup_conn.execute(INIT_SQL)
    register_vector(setup_conn)

    adapter = PgvectorSimilarityAdapter(TEST_DSN, options=f"-c search_path={schema},public")

    corpus = load_fraud_cases()
    embeddings = adapter._model.encode(
        [case.summary for case in corpus], convert_to_numpy=True, normalize_embeddings=True
    )
    for case, embedding in zip(corpus, embeddings):
        setup_conn.execute(
            "INSERT INTO fraud_cases (case_id, title, category, summary, source_note, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (case.case_id, case.title, case.category, case.summary, case.source_note, embedding),
        )
    setup_conn.close()

    yield adapter

    cleanup_conn = psycopg.connect(TEST_DSN, autocommit=True)
    cleanup_conn.execute(f"DROP SCHEMA {schema} CASCADE")
    cleanup_conn.close()


def test_prosecutor_impersonation_query_ranks_matching_case_first(seeded_adapter):
    transcript = "검찰청 수사관인데 계좌가 범죄에 연루돼서 지금 즉시 안전계좌로 이체해야 한다고 전화왔어"
    matches = seeded_adapter.search(transcript, top_k=3)

    assert matches[0].case.case_id == "FC-001"
    assert matches[0].similarity > 0


def test_parcel_smishing_query_ranks_matching_case_first(seeded_adapter):
    transcript = "택배가 반송된다는 문자를 받았는데 링크를 눌렀더니 앱이 설치됐어요"
    matches = seeded_adapter.search(transcript, top_k=2)

    assert matches[0].case.case_id == "FC-006"


def test_top_k_limits_result_count(seeded_adapter):
    matches = seeded_adapter.search("아무 관련 없는 일상 대화입니다", top_k=2)
    assert len(matches) == 2


def test_results_are_sorted_by_similarity_descending(seeded_adapter):
    matches = seeded_adapter.search("검찰청 수사관인데 지금 즉시 송금하세요", top_k=10)
    scores = [m.similarity for m in matches]
    assert scores == sorted(scores, reverse=True)


def test_ping_succeeds_when_reachable(seeded_adapter):
    seeded_adapter.ping()  # 예외 없이 통과하면 성공


def test_search_reconnects_and_succeeds_after_connection_is_closed(seeded_adapter):
    """postgres 단일 장애점 완화 실측(2026-09-01) 회귀 가드 — apps/api의 동일 테스트와
    같은 이유(그쪽 상단 주석 참고). search()가 vector 타입을 쓰므로, 재연결한 새
    커넥션에도 register_vector가 다시 걸렸는지까지 실제 검색으로 확인한다(ping만으로는
    vector 어댑터가 살아있는지 확인이 안 됨)."""
    seeded_adapter.ping()
    stale_conn = seeded_adapter._conn
    stale_conn.close()

    matches = seeded_adapter.search("검찰청 수사관인데 지금 즉시 송금하세요", top_k=2)

    assert len(matches) == 2
    assert seeded_adapter._conn is not stale_conn
