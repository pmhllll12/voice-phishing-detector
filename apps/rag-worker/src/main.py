# apps/rag-worker 진입점 — F-04(유사사례 매칭)를 지원하는 검색 API.
#
# 헥사고날 계층 구성: domain(FraudCase, 포트 인터페이스) -> application(유스케이스)
# -> infrastructure(임베딩/TF-IDF 어댑터, JSON 데이터 로더, 이 FastAPI 진입점).
#
# v2 구현: postgres+pgvector 없이, 로컬 JSON 합성 데이터셋 + sentence-transformers
# 로컬 임베딩 모델(jhgan/ko-sroberta-multitask) + 코사인 유사도로 동작한다
# (infrastructure/adapters/embedding_similarity_adapter.py 참고). v1(TF-IDF, 순수
# stdlib)은 infrastructure/adapters/tfidf_similarity_adapter.py에 그대로 남아있고,
# RAG_DEBUG_COMPARE=1일 때 비교 로그용으로 재사용된다. 나중에 pgvector로 옮길 때도
# SimilarCaseSearchService/FraudCaseSearchPort 인터페이스는 그대로 유지된다.

import logging
import os

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from src.application.services import SimilarCaseSearchService
from src.infrastructure.adapters.debug_compare_adapter import DebugCompareAdapter
from src.infrastructure.adapters.embedding_similarity_adapter import EmbeddingSimilarityAdapter
from src.infrastructure.adapters.tfidf_similarity_adapter import TfidfSimilarityAdapter
from src.infrastructure.data_loader import load_fraud_cases

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Voice Phishing RAG Worker")

_corpus = load_fraud_cases()
_embedding_adapter = EmbeddingSimilarityAdapter(_corpus)

# RAG_DEBUG_COMPARE=1: TF-IDF(v1)도 같이 돌려서 임베딩(v2) 결과와 순위를 로그로
# 비교한다. 기본값(꺼짐)에서는 TfidfSimilarityAdapter를 아예 만들지 않는다 — 코퍼스가
# 커지면 이 비교 자체가 비용이라 상시 켜둘 이유가 없다.
if os.getenv("RAG_DEBUG_COMPARE", "").lower() in ("1", "true", "yes"):
    _search_adapter = DebugCompareAdapter(_embedding_adapter, TfidfSimilarityAdapter(_corpus))
else:
    _search_adapter = _embedding_adapter

similar_case_search_service = SimilarCaseSearchService(_search_adapter)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "corpus_size": len(_corpus),
        "embedding_model": _embedding_adapter.model_name,
        "device": _embedding_adapter.device,
    }


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class SearchRequest(BaseModel):
    transcript: str
    top_k: int = 3


@app.post("/api/v1/similar-cases")
async def search_similar_cases(req: SearchRequest) -> dict:
    matches = similar_case_search_service.execute(req.transcript, req.top_k)
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


# TODO: 데이터셋이 커지거나 postgres+pgvector로 옮길 때는
#       infrastructure/data_loader.py와 embedding_similarity_adapter.py만 교체
# TODO: F-05 판정 근거 문장 생성 시 이 엔드포인트의 결과(사례 요약 + 유사도)를 활용
