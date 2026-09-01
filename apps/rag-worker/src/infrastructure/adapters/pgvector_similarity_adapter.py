# F-04 pgvector 이전 구현체: 코퍼스 임베딩을 프로세스 메모리(v2
# EmbeddingSimilarityAdapter의 self._doc_embeddings numpy 행렬)가 아니라 postgres
# (pgvector 확장, fraud_cases 테이블)에 저장하고 SQL로 코사인 거리 검색한다. domain/
# ports.py의 FraudCaseSearchPort를 구현한다 (v2 EmbeddingSimilarityAdapter와 인터페이스
# 동일 — main.py 배선만 바꾸면 교체된다).
#
# 바뀌는 것은 "코퍼스 임베딩을 어디에 보관/검색하는가"이지 "어떻게 계산하는가"가 아니다.
# 쿼리 임베딩은 여전히 이 프로세스에서 로컬 sentence-transformers 모델
# (jhgan/ko-sroberta-multitask)로 매 요청 계산한다 — postgres에는 쿼리를 텍스트로
# 보내는 게 아니라 계산된 벡터를 보낸다.
#
# 코퍼스는 apps/rag-worker/scripts/seed_fraud_cases.py로 fraud_cases.json ->
# postgres에 미리 적재해둬야 한다. init.sql은 스키마만 만들고 데이터는 넣지 않는다.
#
# 코사인 거리 <-> 유사도: pgvector의 `<=>` 연산자는 코사인 거리(1 - cosine similarity)를
# 반환한다. encode()에서 normalize_embeddings=True로 정규화해뒀으므로 `1 - distance`가
# 그대로 코사인 유사도다 (v2의 내적 방식과 결과가 동일해야 한다 — 부동소수점 오차 수준
# 차이만 남는다).
#
# 연결 관리: apps/api의 PostgresCallLogRepository와 동일한 패턴 — 연결은 __init__이
# 아니라 첫 실제 검색 시점에 1회만 맺고(autocommit) 재사용한다. __init__에서 바로
# 연결하면 main.py가 모듈 스코프에서 인스턴스화할 때 postgres가 항상 떠 있어야 하는
# 문제가 생긴다. 재연결(postgres 단일 장애점 완화, 2026-09-01)도 apps/api와 동일한
# 이유/방식 — 재연결한 새 커넥션에도 register_vector를 다시 걸어야 vector 타입
# 어댑팅이 유지된다(까먹기 쉬운 부분이라 명시).
#
# ANN 인덱스(ivfflat/hnsw)는 아직 안 만든다 — 코퍼스가 10건이라 순차 스캔이면 충분하다
# (infra/db/init.sql 참고).

import logging
import time

import psycopg
import torch
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from src.domain.entities import FraudCase, SimilarCaseMatch
from src.infrastructure import metrics

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "jhgan/ko-sroberta-multitask"

_SELECT_COLUMNS = "case_id, title, category, summary, source_note"


def _resolve_device(requested: str | None) -> str:
    if requested:
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


class PgvectorSimilarityAdapter:
    def __init__(
        self,
        dsn: str,
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
        options: str | None = None,
    ):
        self._dsn = dsn
        self._options = options
        self._conn: psycopg.Connection | None = None
        self.model_name = model_name
        self.device = _resolve_device(device)

        load_start = time.perf_counter()
        self._model = SentenceTransformer(model_name, device=self.device)
        load_seconds = time.perf_counter() - load_start
        metrics.model_load_duration_seconds.set(load_seconds)
        metrics.embedding_model_info.info({"model_name": model_name, "device": self.device})
        logger.info(
            "embedding model loaded: model=%s device=%s load_seconds=%.2f",
            model_name,
            self.device,
            load_seconds,
        )

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn, autocommit=True, options=self._options)
        register_vector(conn)
        return conn

    def _get_conn(self) -> psycopg.Connection:
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _execute(self, query: str, params: tuple = ()):
        """OperationalError(연결 끊김)면 재연결(register_vector 재적용 포함) 후 한 번만
        재시도한다."""
        try:
            return self._get_conn().execute(query, params)
        except psycopg.OperationalError:
            self._conn = self._connect()
            return self._conn.execute(query, params)

    def ping(self) -> None:
        """/ready 체크 전용 — 연결이 살아있는지만 확인한다. 예외를 그대로 전파한다."""
        self._execute("SELECT 1")

    def _update_gpu_memory_metric(self) -> None:
        allocated = torch.cuda.memory_allocated() if self.device == "cuda" else 0
        metrics.gpu_memory_allocated_bytes.set(allocated)

    def search(self, query: str, top_k: int) -> list[SimilarCaseMatch]:
        try:
            with metrics.embedding_inference_duration_seconds.time():
                query_embedding = self._model.encode(
                    query,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
            self._update_gpu_memory_metric()

            rows = self._execute(
                f"""
                SELECT {_SELECT_COLUMNS}, 1 - (embedding <=> %s) AS similarity
                FROM fraud_cases
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_embedding, query_embedding, top_k),
            ).fetchall()

            matches = [
                SimilarCaseMatch(
                    case=FraudCase(case_id=row[0], title=row[1], category=row[2], summary=row[3], source_note=row[4]),
                    similarity=float(row[5]),
                )
                for row in rows
            ]
            metrics.embedding_search_requests_total.labels(result="success").inc()
            return matches
        except Exception:
            metrics.embedding_search_requests_total.labels(result="error").inc()
            raise
