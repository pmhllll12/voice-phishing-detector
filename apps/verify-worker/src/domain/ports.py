# domain 계층의 포트(인터페이스). "어떻게 서명/저장하는가"의 구체 구현(Ed25519, 인메모리)은
# infrastructure에 맡기고, application은 이 인터페이스에만 의존한다 — 나중에 저장소를
# postgres로, 서명을 HSM으로, 공개키 조회를 외부 레지스트리로 바꿔도 application은 그대로
# 유지된다(apps/stt-worker의 SpeechToTextPort와 동일한 목적).
#
# 발급(서명)과 검증(공개키)을 서로 다른 포트로 나눈다. 실제 구조에서 개인키는 발급 기관 안에만
# 있고, 검증하는 쪽(국민 앱/검증 서버)은 공개키만 받아 쓴다. 그래서 검증 유스케이스
# (VerifyProofService)는 IssuerSigningPort를 아예 받지 않는다 — 코드 구조상 개인키에 닿을 수
# 없다.

from datetime import datetime
from typing import Protocol

from .entities import Credential, Issuer, Proof


class IssuerSigningPort(Protocol):
    """발급 전용: 기관(issuer_id)의 개인키로 서명한다. 발급 유스케이스만 쓴다."""

    def sign(self, issuer_id: str, payload: bytes) -> bytes:
        """등록되지 않은 issuer_id면 IssuerNotFoundError."""
        ...


class IssuerPublicKeyRegistryPort(Protocol):
    """검증용: 기관별 공개키 조회. 공개키(바이트)와 기관 정보만 담고 개인키는 모른다."""

    def get_issuer(self, issuer_id: str) -> Issuer | None: ...
    def get_public_key(self, issuer_id: str) -> bytes | None: ...
    def list_issuers(self) -> list[Issuer]: ...


class SignatureVerifierPort(Protocol):
    """공개키만으로 서명을 확인한다(상태 없음). 어떤 기관의 공개키를 쓸지는 호출하는 쪽이
    레지스트리에서 골라 넘긴다."""

    def verify(self, public_key: bytes, payload: bytes, signature: bytes) -> bool: ...


class CredentialRepositoryPort(Protocol):
    def add(self, credential: Credential) -> None: ...
    def get(self, credential_id: str) -> Credential | None: ...
    def list_all(self) -> list[Credential]: ...
    def revoke(self, credential_id: str) -> None: ...
    def is_revoked(self, credential_id: str) -> bool: ...


class ProofRepositoryPort(Protocol):
    def add(self, proof: Proof) -> None: ...
    def get_by_code(self, code: str) -> Proof | None: ...

    def mark_used(self, code: str) -> bool:
        """아직 사용되지 않았으면 used로 바꾸고 True, 이미 사용됐으면 False.
        확인과 표시를 한 번에 해야 동시에 같은 코드로 두 번 검증하는 경우에도
        한 번만 성공한다(compare-and-set)."""
        ...


class ClockPort(Protocol):
    """만료 판정용 현재 시각. 테스트에서 시간을 앞으로 돌려 만료 시나리오를 재현하려고 분리했다."""

    def now(self) -> datetime: ...
