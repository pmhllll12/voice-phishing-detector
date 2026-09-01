# apps/rag-worker 진입점 — F-04(유사사례 매칭)를 지원하는 검색 API.
#
# 헥사고날 계층 구성: domain(FraudCase, 포트 인터페이스) -> application(유스케이스)
# -> infrastructure(임베딩/TF-IDF 어댑터, JSON 데이터 로더, 이 FastAPI 진입점).
#
# v3 구현(F-04 pgvector 이전): 코퍼스 임베딩을 프로세스 메모리가 아니라 postgres
# (pgvector 확장, fraud_cases 테이블)에 저장하고 SQL 코사인 거리 검색으로 유사사례를
# 찾는다 (infrastructure/adapters/pgvector_similarity_adapter.py 참고). fraud_cases.json은
# 여전히 소스 오브 트루스로 남아있고 postgres 적재는 scripts/seed_fraud_cases.py가
# 담당한다 — 이 파일에서는 TF-IDF 디버그 비교용 코퍼스와 /health의 corpus_size 표시에만
# JSON을 그대로 쓴다. v2(EmbeddingSimilarityAdapter, 프로세스 메모리에 코퍼스 임베딩을
# 올려두던 방식)는 infrastructure/adapters/embedding_similarity_adapter.py에 남아있으나
# 이제 이 진입점에서는 쓰지 않는다. v1(TF-IDF, 순수 stdlib)은
# infrastructure/adapters/tfidf_similarity_adapter.py에 남아있고 RAG_DEBUG_COMPARE=1일
# 때 비교 로그용으로 재사용된다. SimilarCaseSearchService/FraudCaseSearchPort
# 인터페이스는 v1->v2->v3 내내 그대로 유지된다.

import logging
import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from src.application.services import SimilarCaseSearchService
from src.infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from src.infrastructure.adapters.pgvector_similarity_adapter import PgvectorSimilarityAdapter
from src.infrastructure.adapters.tfidf_similarity_adapter import TfidfSimilarityAdapter
from src.infrastructure.data_loader import load_fraud_cases
from src.infrastructure.readiness import check_embedding_search_ready

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Voice Phishing RAG Worker")

# F-04: 유사사례 pgvector(postgres) 주소. 로컬 기본값은 docker로 띄운 vps-postgres
# 컨테이너 기준 (apps/api/src/main.py DATABASE_URL과 동일한 패턴, infra/db/init.sql,
# run-voice-phishing-detector 스킬 참고).
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://vps_app:vps_dev_password@localhost:5432/vps_detector"
)

_corpus = load_fraud_cases()
_embedding_adapter = PgvectorSimilarityAdapter(DATABASE_URL)

# RAG_DEBUG_COMPARE=1: TF-IDF(v1)도 같이 돌려서 임베딩(v3) 결과와 순위를 로그로
# 비교한다. 기본값(꺼짐)에서는 TfidfSimilarityAdapter를 아예 만들지 않는다 — 코퍼스가
# 커지면 이 비교 자체가 비용이라 상시 켜둘 이유가 없다.
if os.getenv("RAG_DEBUG_COMPARE", "").lower() in ("1", "true", "yes"):
    _search_adapter = DebugCompareAdapter(_embedding_adapter, TfidfSimilarityAdapter(_corpus))
else:
    _search_adapter = _embedding_adapter

similar_case_search_service = SimilarCaseSearchService(_search_adapter)


@app.get("/health")
async def health() -> dict:
    # corpus_size는 fraud_cases.json(source of truth) 기준이다 — postgres에
    # scripts/seed_fraud_cases.py로 실제 적재됐는지는 이 값으로 알 수 없고 /ready가
    # 진짜 검색(postgres 왕복)까지 확인한다.
    return {
        "status": "ok",
        "corpus_size": len(_corpus),
        "embedding_model": _embedding_adapter.model_name,
        "device": _embedding_adapter.device,
    }


@app.get("/ready")
def ready() -> JSONResponse:
    check = check_embedding_search_ready(similar_case_search_service, _embedding_adapter.device)
    status_code = 200 if check["status"] == "ok" else 503
    return JSONResponse(
        content={"status": "ok" if check["status"] == "ok" else "error", "checks": {"embedding_search": check}},
        status_code=status_code,
    )


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class SearchRequest(BaseModel):
    transcript: str
    top_k: int = 3


@app.post("/api/v1/similar-cases")
async def search_similar_cases(req: SearchRequest) -> dict:
    """N-05 동시성 SLA 대응(2026-09-01) — apps/mcp-server/src/rest_server.py의 동일
    주석 참고: SimilarCaseSearchService.execute()는 동기 코드(GPU 임베딩 인코딩 +
    psycopg 쿼리)라 그냥 부르면 이 프로세스의 이벤트 루프를 막는다. mcp-server가
    F-04 결합을 위해 이 엔드포인트를 호출하는 경로에서 이중으로 직렬화되는 걸
    막기 위해 스레드풀에 위임한다."""
    matches = await run_in_threadpool(similar_case_search_service.execute, req.transcript, req.top_k)
    return {
        "matches": [
            {
                "case_id": m.case.case_id,
                "title": m.case.title,
                "category": m.case.category,
                "summary": m.case.summary,
                "source_note": m.case.source_note,
                "similarity": round(m.similarity, 4),
            }
            for m in matches
        ]
    }


# TODO: F-05 판정 근거 문장 생성 시 이 엔드포인트의 결과(사례 요약 + 유사도)를 활용
