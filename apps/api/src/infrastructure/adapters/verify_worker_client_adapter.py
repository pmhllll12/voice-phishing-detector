# 역방향 신원확인 POC: 국민이 입력한 코드를 verify-worker(/api/v1/verify)에 HTTP로
# 위임하는 어댑터. domain/ports.py의 IdentityVerificationPort를 구현한다
# (stt_client_adapter.py와 동일한 패턴). verify-worker는 실제 모바일신분증과 연동하지
# 않는 모의 시제품이다.
#
# verify-worker가 로컬에서 미리 실행 중이어야 한다:
#   cd apps/verify-worker && source .venv/bin/activate
#   uvicorn src.main:app --port 8400

import httpx


class VerifyWorkerClientAdapter:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._base_url = base_url
        self._timeout = timeout

    def verify(self, code: str) -> dict:
        response = httpx.post(f"{self._base_url}/api/v1/verify", json={"code": code}, timeout=self._timeout)
        response.raise_for_status()
        return response.json()
