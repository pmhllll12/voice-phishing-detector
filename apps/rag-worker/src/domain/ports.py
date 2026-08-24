# domain 계층의 포트(인터페이스). "어떻게 검색하는가"의 구체 구현은 infrastructure에
# 맡기고, application은 이 인터페이스에만 의존한다 — 나중에 검색 알고리즘을
# TF-IDF에서 실제 임베딩/pgvector로 바꿔도 application 코드는 그대로 유지된다.

from typing import Protocol

from .entities import SimilarCaseMatch


class FraudCaseSearchPort(Protocol):
    def search(self, query: str, top_k: int) -> list[SimilarCaseMatch]: ...
