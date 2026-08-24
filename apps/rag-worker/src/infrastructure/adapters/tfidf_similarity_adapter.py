# F-04 v1 구현체: 외부 임베딩 API/모델 없이, 문자 bigram 기반 TF-IDF + 코사인 유사도로
# 유사 사기사례를 검색하는 어댑터. domain/ports.py의 FraudCaseSearchPort를 구현한다.
#
# WHY 문자 n-gram인가: 한국어는 조사가 붙는 교착어라 공백 기준 단어 토큰화만으로는
# 매칭 정확도가 떨어진다 (예: "계좌를", "계좌로", "계좌가"는 같은 "계좌" 의미인데
# 공백 토큰화로는 서로 다른 토큰이 됨). 형태소 분석기(KoNLPy/mecab 등) 설치 없이도
# 어느 정도 견고하게 동작하도록 2-gram(bigram) 문자 단위로 쪼개서 벡터화했다.
#
# TODO: 정확도가 부족하면
#   (1) KoNLPy 등 형태소 분석기 도입
#   (2) sentence-transformers 등 실제 임베딩 모델 + pgvector로 교체
# — 이 어댑터의 인터페이스(FraudCaseSearchPort)는 그대로 유지한 채 구현체만
#   갈아끼울 수 있도록 설계했다 (N-06 확장성).

import math
from collections import Counter

from src.domain.entities import FraudCase, SimilarCaseMatch


def _char_bigrams(text: str) -> list[str]:
    normalized = text.replace(" ", "")
    if len(normalized) < 2:
        return [normalized] if normalized else []
    return [normalized[i : i + 2] for i in range(len(normalized) - 1)]


class TfidfSimilarityAdapter:
    def __init__(self, corpus: list[FraudCase]):
        self._corpus = corpus
        term_counts_per_doc = [Counter(_char_bigrams(c.summary)) for c in corpus]
        self._idf = self._compute_idf(term_counts_per_doc)
        self._doc_vectors = [self._tfidf_vector(tc) for tc in term_counts_per_doc]

    def _compute_idf(self, doc_term_counts: list[Counter]) -> dict[str, float]:
        n_docs = len(doc_term_counts)
        doc_freq: Counter = Counter()
        for term_counts in doc_term_counts:
            doc_freq.update(term_counts.keys())
        # +1 스무딩: 학습 데이터에 없던 bigram이 나와도 0으로 나눠지지 않게 함
        return {term: math.log((n_docs + 1) / (freq + 1)) + 1 for term, freq in doc_freq.items()}

    def _default_idf(self) -> float:
        return math.log(len(self._corpus) + 1) + 1

    def _tfidf_vector(self, term_counts: Counter) -> dict[str, float]:
        total = sum(term_counts.values()) or 1
        return {
            term: (count / total) * self._idf.get(term, self._default_idf())
            for term, count in term_counts.items()
        }

    @staticmethod
    def _cosine_similarity(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
        common_terms = set(vec_a) & set(vec_b)
        dot = sum(vec_a[t] * vec_b[t] for t in common_terms)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def search(self, query: str, top_k: int) -> list[SimilarCaseMatch]:
        query_vector = self._tfidf_vector(Counter(_char_bigrams(query)))

        scored = [
            SimilarCaseMatch(case=case, similarity=self._cosine_similarity(query_vector, doc_vector))
            for case, doc_vector in zip(self._corpus, self._doc_vectors)
        ]
        scored.sort(key=lambda m: m.similarity, reverse=True)
        return scored[:top_k]
