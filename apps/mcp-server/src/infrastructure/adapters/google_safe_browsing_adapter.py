# 우선순위 2(선택 항목): 문자/이메일 속 URL을 Google Safe Browsing API v4로 실제
# 악성 URL 목록과 대조한다. domain/ports.py의 ThreatIntelligencePort를 구현한다.
#
# API 키: https://developers.google.com/safe-browsing 에서 무료(비상업적 용도)로
# 발급받는다 — GOOGLE_SAFE_BROWSING_API_KEY 환경변수로 주입(server.py/rest_server.py
# 참고). 키가 없으면 이 어댑터 자체를 안 만들고 threat_intelligence_port=None으로
# 두면 된다(FraudCaseSearchPort와 동일한 선택적 의존 패턴).
#
# ⚠️ 한계(정직하게 밝힘): entity_extraction.py가 URL을 host로만 정규화하기 때문에
# (경로/쿼리스트링은 버림 — 크로스채널 매칭에는 host만으로 충분하고, path까지 저장하면
# 오히려 같은 도메인의 다른 URL을 별개 엔티티로 취급해 매칭을 놓친다), 이 어댑터가
# Safe Browsing에 실제로 보내는 건 원본 URL이 아니라 "http://{host}/"로 재구성한
# 값이다. Safe Browsing이 특정 경로만 악성으로 등재한 경우(도메인 자체는 깨끗한 경우)
# 는 놓칠 수 있고, 반대로 도메인 전체가 등재된 경우는 정상적으로 잡는다 — 크로스채널
# 상관관계가 애초에 "도메인 재사용"을 근거로 삼는 기능이라는 점과 일관된 트레이드오프다.
#
# 실패 시 예외를 올리지 않고 빈 리스트로 폴백한다 — RagWorkerSearchAdapter와 같은 이유로,
# 이 검사는 "있으면 근거를 더 풍부하게" 수준이지 판정의 필수 의존이 아니다.

import logging

import httpx

logger = logging.getLogger(__name__)

_API_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
_THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]


class GoogleSafeBrowsingAdapter:
    def __init__(self, api_key: str, timeout: float = 5.0):
        self._api_key = api_key
        self._timeout = timeout

    def check_urls(self, urls: list[str]) -> list[str]:
        if not urls:
            return []

        entries = [{"url": f"http://{host}/"} for host in urls]
        try:
            response = httpx.post(
                _API_URL,
                params={"key": self._api_key},
                json={
                    "client": {"clientId": "voice-phishing-detector", "clientVersion": "1.0.0"},
                    "threatInfo": {
                        "threatTypes": _THREAT_TYPES,
                        "platformTypes": ["ANY_PLATFORM"],
                        "threatEntryTypes": ["URL"],
                        "threatEntries": entries,
                    },
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Google Safe Browsing 조회 실패 — 악성 URL 검사 없이 진행: %s", e)
            return []

        matches = response.json().get("matches", [])
        flagged_urls = {m["threat"]["url"] for m in matches if "threat" in m and "url" in m["threat"]}
        # 응답의 url은 "http://{host}/" 형태이므로 원래 host 목록과 다시 대조해 반환한다.
        return [host for host in urls if f"http://{host}/" in flagged_urls]
