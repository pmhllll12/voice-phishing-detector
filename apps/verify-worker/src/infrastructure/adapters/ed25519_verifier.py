# infrastructure 계층: SignatureVerifierPort의 Ed25519 구현 — 검증 측 전용.
#
# 공개키 바이트(레지스트리에서 조회한 것)만으로 서명을 확인한다. 상태가 없고 개인키를 다루는
# 코드가 없다. 공개키 형식이 잘못됐거나(32바이트가 아님) 서명이 맞지 않으면 False.

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class Ed25519SignatureVerifier:
    def verify(self, public_key: bytes, payload: bytes, signature: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, payload)
            return True
        except (InvalidSignature, ValueError):
            return False
