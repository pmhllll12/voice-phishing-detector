# infrastructure 계층: CredentialSignerPort의 Ed25519 구현(cryptography 패키지).
#
# 모의 기관별 키쌍을 처음 서명할 때 메모리에서 생성한다 — 실제 기관의 키나 실제
# 모바일신분증 발급 체계와는 무관하고, 프로세스를 재시작하면 키가 새로 만들어져 기존
# 자격증명은 전부 signature_invalid가 된다(저장소도 인메모리라 실제로는 함께 사라진다).
#
# WHY Ed25519: 서명/검증이 빠르고(국민이 코드를 넣는 순간 바로 판정해야 함), 키와 서명이
# 짧으며(공개키 32바이트, 서명 64바이트), 파라미터 선택 실수의 여지가 없다.

import threading

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class Ed25519CredentialSigner:
    def __init__(self):
        self._keys: dict[str, Ed25519PrivateKey] = {}
        self._lock = threading.Lock()

    def _key_for(self, institution_name: str) -> Ed25519PrivateKey:
        with self._lock:
            if institution_name not in self._keys:
                self._keys[institution_name] = Ed25519PrivateKey.generate()
            return self._keys[institution_name]

    def sign(self, institution_name: str, payload: bytes) -> bytes:
        return self._key_for(institution_name).sign(payload)

    def verify(self, institution_name: str, payload: bytes, signature: bytes) -> bool:
        # 검증은 공개키만으로 한다 — 실제 구조라면 검증 측은 개인키 없이 기관 공개키만
        # 조회해서 확인한다. 등록되지 않은 기관이면(키가 없으면) 무조건 실패.
        with self._lock:
            private_key = self._keys.get(institution_name)
        if private_key is None:
            return False
        try:
            private_key.public_key().verify(signature, payload)
            return True
        except InvalidSignature:
            return False
