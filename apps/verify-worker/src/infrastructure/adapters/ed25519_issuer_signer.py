# infrastructure 계층: IssuerSigningPort의 Ed25519 구현(cryptography 패키지) — 발급 측 전용.
#
# 모의 기관별 키쌍을 기동 시 메모리에서 만든다(create_key). 개인키는 이 객체 밖으로 나가지
# 않고, 밖으로 내보내는 건 공개키 바이트뿐이다 — main.py가 그 공개키를 레지스트리
# (in_memory_issuer_registry.py)에 등록하고, 검증 쪽은 레지스트리만 본다. 실제 기관의 키나
# 실제 모바일신분증 발급 체계와는 무관하고, 프로세스를 재시작하면 키가 새로 만들어진다
# (저장소도 인메모리라 기존 자격증명도 함께 사라진다).
#
# WHY Ed25519: 서명/검증이 빠르고(국민이 코드를 넣는 순간 바로 판정해야 함), 키와 서명이
# 짧으며(공개키 32바이트, 서명 64바이트), 파라미터 선택 실수의 여지가 없다.

import threading

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.domain.entities import IssuerNotFoundError


class Ed25519IssuerSigner:
    def __init__(self):
        self._keys: dict[str, Ed25519PrivateKey] = {}
        self._lock = threading.Lock()

    def create_key(self, issuer_id: str) -> bytes:
        """기관 키쌍을 만들고 공개키(raw 32바이트)만 돌려준다. 이미 있으면 거부한다 — 같은
        issuer_id의 키가 조용히 바뀌면 그 기관이 발급한 기존 자격증명이 전부 무효가 된다."""
        with self._lock:
            if issuer_id in self._keys:
                raise ValueError(f"이미 키가 있는 기관입니다: {issuer_id}")
            key = Ed25519PrivateKey.generate()
            self._keys[issuer_id] = key
        return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, issuer_id: str, payload: bytes) -> bytes:
        with self._lock:
            key = self._keys.get(issuer_id)
        if key is None:
            raise IssuerNotFoundError(issuer_id)
        return key.sign(payload)
