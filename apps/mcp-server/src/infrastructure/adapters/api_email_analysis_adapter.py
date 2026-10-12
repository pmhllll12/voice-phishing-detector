# 우선순위 2(SMS/email 실채널 연동): Gmail 폴러가 판정 결과를 apps/api로 보내
# 감사증적(postgres)에 남기고 F-06 대시보드(이메일 탭)에 노출되게 한다.
# domain/ports.py의 EmailAnalysisSinkPort를 구현한다.
#
# WHY mcp-server 안에서 직접 postgres에 적재하지 않는가: call_analysis_results는
# N-01상 apps/api가 소유하는 테이블이다(masking/RBAC/집계 로직도 전부 apps/api에
# 있음) — mcp-server가 그 테이블에 직접 쓰면 소유권 경계가 흐려진다. apps/api가
# 이미 노출하는 POST /api/v1/calls/analyze를 그대로 호출하는 쪽이(channel="email"
# 태그만 붙여서) 기존 통화 판정 경로와 완전히 같은 코드 경로(마스킹→판정→상관관계→
# 적재)를 타게 만든다.

import logging

import httpx

logger = logging.getLogger(__name__)


class ApiEmailAnalysisAdapter:
    def __init__(self, api_base_url: str, api_key: str, timeout: float = 60.0):
        self._api_base_url = api_base_url
        self._api_key = api_key
        self._timeout = timeout

    def analyze(self, text: str, channel, occurred_at) -> dict:
        response = httpx.post(
            f"{self._api_base_url}/api/v1/calls/analyze",
            json={"transcript": text, "channel": channel.value, "occurred_at": occurred_at.isoformat()},
            headers={"X-API-Key": self._api_key},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()
