# apps/rag-worker 진입점 — F-04(유사사례 매칭)를 지원하는 검색 API.
#
# 헥사고날 계층 구성: domain(FraudCase, 포트 인터페이스) -> application(유스케이스)
# -> infrastructure(TF-IDF 어댑터, JSON 데이터 로더, 이 FastAPI 진입점).
#
# v1 구현: postgres+pgvector 없이, 로컬 JSON 합성 데이터셋 + 문자 bigram TF-IDF
# 코사인 유사도로 동작한다 (infrastructure/adapters/tfidf_similarity_adapter.py 참고).
# 나중에 pgvector로 옮길 때도 SimilarCaseSearchService/FraudCaseSearchPort 인터페이스는
# 그대로 유지된다.

from fastapi import FastAPI
from pydantic import BaseModel

from src.application.services import SimilarCaseSearchService
from src.infrastructure.adapters.tfidf_similarity_adapter import TfidfSimilarityAdapter
from src.infrastructure.data_loader import load_fraud_cases

app = FastAPI(title="Voice Phishing RAG Worker")

_corpus = load_fraud_cases()
_search_adapter = TfidfSimilarityAdapter(_corpus)
similar_case_search_service = SimilarCaseSearchService(_search_adapter)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "corpus_size": len(_corpus)}


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
#       infrastructure/data_loader.py와 tfidf_similarity_adapter.py만 교체
# TODO: F-05 판정 근거 문장 생성 시 이 엔드포인트의 결과(사례 요약 + 유사도)를 활용
