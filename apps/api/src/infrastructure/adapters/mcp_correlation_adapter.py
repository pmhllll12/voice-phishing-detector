# 우선순위 2(크로스채널 상관관계 탐지)를 mcp-server(/api/v1/correlate)에 HTTP로
# 위임하는 어댑터. domain/ports.py의 MultichannelCorrelationPort를 구현한다.
# McpServerCallAnalysisAdapter와 같은 패턴/N-02 인증(서비스 자격증명) — 그쪽 상단
# 주석 참고.
#
# ⚠️ entities만 보내고 raw_transcript는 절대 보내지 않는다 — N-03이 막으려는 것과
# 같은 종류의 노출(로컬이라도 원문이 필요 이상으로 다른 프로세스로 나가는 것)을
# 피하기 위한 설계다(docs/design.md 7장 참고). 실패해도(mcp-server 다운 등) 예외를
# 올리지 않고 빈 결과로 폴백한다 — RagWorkerSearchAdapter와 같은 이유로, 크로스채널
# 상관관계는 "있으면 근거를 더 풍부하게" 수준이지 판정의 필수 의존이 아니다.

import logging

import httpx

logger = logging.getLogger(__name__)

_EMPTY_RESULT = {
    "matches": [],
    "match_count": 0,
    "risk_boost": 0,
    "reasons": [],
    "updated_risk_score": None,
    "updated_risk_level": None,
}


class McpCorrelationAdapter:
    def __init__(self, base_url: str, service_api_key: str, timeout: float = 10.0):
        self._base_url = base_url
        self._service_api_key = service_api_key
        self._timeout = timeout

    def correlate(
        self,
        channel: str,
        entities: list[dict],
        occurred_at: str,
        context_excerpt: str,
        current_risk_score: int,
        source_ref: str | None = None,
    ) -> dict:
        try:
            response = httpx.post(
                f"{self._base_url}/api/v1/correlate",
                json={
                    "channel": channel,
                    "entities": entities,
                    "occurred_at": occurred_at,
                    "context_excerpt": context_excerpt,
                    "current_risk_score": current_risk_score,
                    "source_ref": source_ref,
                },
                headers={"X-API-Key": self._service_api_key},
                timeout=self._timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.warning(
                "mcp-server(%s) 크로스채널 상관관계 조회 실패 — 결합 없이 진행: %s", self._base_url, e
            )
            return dict(_EMPTY_RESULT)
