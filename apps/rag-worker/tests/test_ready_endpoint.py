# /ready는 외부 서비스 없이 실제 검색 서비스를 1건 호출해 자가 점검한다 —
# src/infrastructure/readiness.py 참고. main.py가 아니라 readiness.py에서 직접
# import하는 이유: main.py를 import하면 EmbeddingSimilarityAdapter가 실제
# sentence-transformers 모델을 로드해버려서(실측 약 20초, HF Hub 네트워크 호출
# 포함) 이 테스트가 무겁고 네트워크 의존적으로 바뀐다.

from src.application.services import SimilarCaseSearchService
from src.infrastructure.readiness import check_embedding_search_ready as _check_embedding_search_ready


class _WorkingAdapter:
    def search(self, query: str, top_k: int):
        return []


class _BrokenAdapter:
    def search(self, query: str, top_k: int):
        raise RuntimeError("CUDA error: out of memory")


def test_ready_ok_when_search_succeeds():
    service = SimilarCaseSearchService(_WorkingAdapter())

    result = _check_embedding_search_ready(service, device="cpu")

    assert result["status"] == "ok"


def test_ready_error_when_search_raises():
    service = SimilarCaseSearchService(_BrokenAdapter())

    result = _check_embedding_search_ready(service, device="cpu")

    assert result["status"] == "error"
    assert "RuntimeError" in result["detail"]
