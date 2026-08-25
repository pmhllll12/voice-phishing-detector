# F-04 v2 구현체: sentence-transformers 로컬 임베딩 모델(기본값 jhgan/ko-sroberta-multitask)
# + 코사인 유사도로 유사 사기사례를 검색하는 어댑터. domain/ports.py의
# FraudCaseSearchPort를 구현한다 (v1 TfidfSimilarityAdapter와 인터페이스 동일).
#
# WHY 이 모델인가: 한국어 문장 유사도(STS) 벤치마크로 검증된 sentence-transformers
# 호환 모델 중 가장 널리 쓰이는 선택지 — SentenceTransformer(model_name) 한 줄로
# 바로 로드된다 (KoSimCSE 계열은 pooling을 직접 구현해야 해서 제외).
#
# WHY 코사인 유사도를 v1(dict 기반 TF-IDF 벡터)과 공유하지 않는가: TF-IDF 벡터는
# {bigram: weight} 형태의 희소 dict이고, 임베딩 벡터는 고정 차원(768) 밀집 벡터라
# 표현 방식 자체가 다르다. 임베딩 벡터를 미리 정규화(normalize_embeddings=True)해두면
# 코사인 유사도가 단순 내적(dot product)과 같아지므로, numpy 행렬곱 한 번으로 코퍼스
# 전체와의 유사도를 계산한다 — dict 순회보다 훨씬 빠르고 자연스러운 방식이다.
#
# 배치 처리: 코퍼스 임베딩은 __init__에서 전체를 한 번에 batch encode한다 (요청마다
# 다시 계산하지 않음). 쿼리는 검색 요청 1건당 1문장이라 배치가 필요 없지만, 나중에
# 여러 쿼리를 한 번에 받는 API가 생기면 search()를 리스트 입력으로 확장하면 된다.
#
# 캐싱: 모델 로딩(SentenceTransformer(...))은 이 클래스가 인스턴스화될 때 1회만
# 일어난다. main.py에서 모듈 레벨 싱글턴으로 만들어 서버 생명주기 동안 재사용한다
# (기존 TfidfSimilarityAdapter/코퍼스 로딩과 동일한 패턴).

import logging
import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from src.domain.entities import FraudCase, SimilarCaseMatch
from src.infrastructure import metrics

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "jhgan/ko-sroberta-multitask"


def _resolve_device(requested: str | None) -> str:
    if requested:
        return requested
    return "cuda" if torch.cuda.is_available() else "cpu"


class EmbeddingSimilarityAdapter:
    def __init__(
        self,
        corpus: list[FraudCase],
        model_name: str = DEFAULT_MODEL_NAME,
        device: str | None = None,
    ):
        self._corpus = corpus
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

        # normalize_embeddings=True: 벡터 길이를 1로 맞춰서, 이후 코사인 유사도를
        # 내적(dot product)만으로 계산할 수 있게 한다.
        self._doc_embeddings = self._model.encode(
            [case.summary for case in corpus],
            batch_size=32,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        self._update_gpu_memory_metric()

    def _update_gpu_memory_metric(self) -> None:
        allocated = torch.cuda.memory_allocated() if self.device == "cuda" else 0
        metrics.gpu_memory_allocated_bytes.set(allocated)

    def search(self, query: str, top_k: int) -> list[SimilarCaseMatch]:
        try:
            with metrics.embedding_inference_duration_seconds.time():
                query_embedding = self._model.encode(
                    [query],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )[0]
            self._update_gpu_memory_metric()

            similarities: np.ndarray = self._doc_embeddings @ query_embedding
            top_indices = np.argsort(-similarities)[:top_k]

            matches = [
                SimilarCaseMatch(case=self._corpus[i], similarity=float(similarities[i]))
                for i in top_indices
            ]
            metrics.embedding_search_requests_total.labels(result="success").inc()
            return matches
        except Exception:
            metrics.embedding_search_requests_total.labels(result="error").inc()
            raise
