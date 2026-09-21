# N-02 접근통제(mcp-server 확장): X-API-Key 헤더 -> Role(조회/처리/관리자) 조회 후
# FastAPI dependency로 rest_server.py의 라우트를 보호한다.
# apps/api/src/infrastructure/adapters/api_key_role_auth.py와 동일한 패턴/한계를
# 따른다 — 그쪽 상단 주석 참고(로그인/세션/JWT 없음, 환경변수 기반 키 저장소).
#
# 이 REST 어댑터는 apps/api(McpServerCallAnalysisAdapter/McpServerReportAdapter)가
# 서비스 대 서비스로 호출하는 게 기본 경로다 — 그래서 DEFAULT_API_KEYS는 apps/api와
# **완전히 같은 값**을 쓴다("dev-handler-key" 등). 실제 서비스라면 서비스별로 다른
# 키를 발급해야 하지만, 이 포트폴리오 규모(로컬 개발, 두 서비스가 같은 사람이 관리)에서는
# 값을 맞춰두는 쪽이 "DATABASE_URL 기본값을 api/mcp-server가 그대로 공유하는" 기존
# 패턴과 일관되고 설정 실수 여지도 줄어든다 — 알고 하는 단순화임을 명시해둔다.
#
# MCP stdio 진입점(server.py)에는 이 인증을 적용하지 않는다 — Claude Code가 로컬
# 서브프로세스로 직접 띄우는 신뢰된 실행 경로라 네트워크 인증 모델이 잘 안 맞는다
# (이미 그 프로세스를 실행할 수 있는 사람은 전체 신뢰를 갖는다). REST 어댑터(rest_server.py,
# docker-compose로 8100 포트가 외부에도 열림)만 이 인증의 대상이다.

import os

from fastapi import Header, HTTPException

from domain.entities import Role, role_satisfies

# apps/api/src/infrastructure/adapters/api_key_role_auth.py의 DEFAULT_API_KEYS와
# 의도적으로 동일한 값 — 위 모듈 주석 참고.
DEFAULT_API_KEYS = "dev-viewer-key:viewer,dev-handler-key:handler,dev-admin-key:admin"


def _parse_api_keys(raw: str) -> dict[str, Role]:
    keys: dict[str, Role] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, role_value = pair.partition(":")
        keys[key] = Role(role_value)
    return keys


API_KEYS = _parse_api_keys(os.environ.get("API_KEYS", DEFAULT_API_KEYS))


def require_role(minimum: Role):
    """minimum 이상 권한을 가진 X-API-Key만 통과시키는 dependency를 만든다. 키가 없거나
    모르는 키면 401(인증 실패), 키는 유효하지만 권한이 부족하면 403(인가 실패)을 던진다."""

    def _dependency(x_api_key: str | None = Header(default=None)) -> Role:
        if x_api_key is None or x_api_key not in API_KEYS:
            raise HTTPException(status_code=401, detail="유효한 X-API-Key 헤더가 필요합니다.")
        role = API_KEYS[x_api_key]
        if not role_satisfies(role, minimum):
            raise HTTPException(
                status_code=403,
                detail=f"이 작업은 {minimum.value} 이상 권한이 필요합니다 (현재 키 권한: {role.value}).",
            )
        return role

    return _dependency
