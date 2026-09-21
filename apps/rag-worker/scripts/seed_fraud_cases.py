# F-04 pgvector 이전: fraud_cases.json(합성 데이터셋, source of truth)을 읽어 각 사례의
# summary를 로컬 임베딩 모델(jhgan/ko-sroberta-multitask)로 인코딩한 뒤 postgres의
# fraud_cases 테이블에 upsert한다. infra/db/init.sql은 스키마만 만들고 데이터는 넣지
# 않으므로, postgres를 새로 띄우거나 데이터셋을 갱신할 때마다 이 스크립트를 다시
# 실행해야 한다 (case_id가 PK라 재실행해도 안전 — ON CONFLICT DO UPDATE).
#
# 실행 (apps/rag-worker 디렉터리에서):
#   .venv/bin/python -m scripts.seed_fraud_cases

import os

import psycopg
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from src.infrastructure.adapters.pgvector_similarity_adapter import DEFAULT_MODEL_NAME
from src.infrastructure.data_loader import load_fraud_cases

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)


def seed(dsn: str = DATABASE_URL, model_name: str = DEFAULT_MODEL_NAME) -> int:
    corpus = load_fraud_cases()
    model = SentenceTransformer(model_name)
    embeddings = model.encode(
        [case.summary for case in corpus],
        batch_size=32,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    conn = psycopg.connect(dsn, autocommit=True)
    register_vector(conn)
    try:
        for case, embedding in zip(corpus, embeddings):
            conn.execute(
                """
                INSERT INTO fraud_cases (case_id, title, category, summary, source_note, embedding)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    summary = EXCLUDED.summary,
                    source_note = EXCLUDED.source_note,
                    embedding = EXCLUDED.embedding
                """,
                (case.case_id, case.title, case.category, case.summary, case.source_note, embedding),
            )
    finally:
        conn.close()
    return len(corpus)


if __name__ == "__main__":
    count = seed()
    print(f"seeded {count} fraud cases into postgres (fraud_cases table)")
