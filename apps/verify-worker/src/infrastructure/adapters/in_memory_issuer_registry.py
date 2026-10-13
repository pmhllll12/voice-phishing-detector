# infrastructure 계층: IssuerPublicKeyRegistryPort의 인메모리 구현 — 기관별 공개키 레지스트리.
#
# 기관 정보와 공개키 바이트만 담는다. 개인키 객체는 받지도 않으므로(register가 bytes만 받음)
# 이 레지스트리를 쓰는 검증 유스케이스는 구조상 서명을 만들 수 없다. 실제 구조라면 기관이
# 공개키를 공개 레지스트리에 등록하고 검증 측은 그걸 조회해 캐시하겠지만, 이 POC는 같은
# 프로세스 메모리에 두며 재시작하면 사라진다.

import threading

from src.domain.entities import Issuer


class InMemoryIssuerPublicKeyRegistry:
    def __init__(self):
        self._issuers: dict[str, Issuer] = {}
        self._public_keys: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def register(self, issuer: Issuer, public_key: bytes) -> None:
        if not isinstance(public_key, bytes):
            raise TypeError("레지스트리에는 공개키 바이트만 등록한다")
        with self._lock:
            self._issuers[issuer.issuer_id] = issuer
            self._public_keys[issuer.issuer_id] = public_key

    def get_issuer(self, issuer_id: str) -> Issuer | None:
        with self._lock:
            return self._issuers.get(issuer_id)

    def get_public_key(self, issuer_id: str) -> bytes | None:
        with self._lock:
            return self._public_keys.get(issuer_id)

    def list_issuers(self) -> list[Issuer]:
        with self._lock:
            return list(self._issuers.values())
