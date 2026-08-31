# N-02 접근통제: X-API-Key 헤더 -> Role(조회/처리/관리자) 조회 후 FastAPI dependency로
# 라우트를 보호한다. 별도 사용자 시스템(로그인/세션/JWT)은 아직 없다 — 이 프로젝트
# 규모(단일 대시보드, 소수 운영자)에서는 발급된 키에 역할을 고정 매핑하는 것으로 충분하고,
# 사용자별 계정이 필요해지면(예: 감사증적에 "누가 처리했는지" 남겨야 하는 요구사항이
# 생기면) 그때 이 어댑터를 JWT/세션 기반으로 교체한다 — Role.role_satisfies() 계층
# 구조와 require_role() 시그니처는 그대로 유지될 것이다.
#
# 키 저장소도 아직 postgres가 아니라 환경변수다 — DATABASE_URL/API_KEYS 둘 다 "로컬
# 개발 전용 기본값 + 환경변수로 오버라이드" 패턴(main.py 상단 주석과 동일)이고, 키
# 회전/폐기가 필요해지면(감사증적처럼 "누가 언제 어떤 키를 썼는지" 추적이 필요해지면)
# postgres 테이블로 옮긴다.

import os

from fastapi import Header, HTTPException

from src.domain.entities import Role, role_satisfies

# 로컬 개발 전용 기본 키 3종(역할별 1개) — 프로덕션에서는 반드시 API_KEYS 환경변수로
# 교체할 것(DATABASE_URL과 동일한 패턴). 형식: "key1:role1,key2:role2,..."
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
