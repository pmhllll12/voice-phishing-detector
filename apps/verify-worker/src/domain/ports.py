# domain 계층의 포트(인터페이스). "어떻게 서명/저장하는가"의 구체 구현(Ed25519, 인메모리)은
# infrastructure에 맡기고, application은 이 인터페이스에만 의존한다 — 나중에 저장소를
# postgres로, 서명을 HSM/외부 발급기관 공개키 조회로 바꿔도 application은 그대로 유지된다
# (apps/stt-worker의 SpeechToTextPort와 동일한 목적).

from datetime import datetime
from typing import Protocol

from .entities import Credential, Proof


class CredentialSignerPort(Protocol):
    """모의 기관의 서명/검증. 기관명별로 서로 다른 키쌍을 쓴다."""

    def sign(self, institution_name: str, payload: bytes) -> bytes: ...
    def verify(self, institution_name: str, payload: bytes, signature: bytes) -> bool: ...


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
