# infrastructure 계층: 자격증명/증명/폐기 목록의 인메모리 저장소.
# POC 범위라 프로세스 재시작 시 전부 사라진다 — 영속화가 필요해지면 같은 포트
# (CredentialRepositoryPort/ProofRepositoryPort)의 postgres 구현을 추가하면 된다.

import threading
from datetime import datetime, timezone

from src.domain.entities import Credential, Proof


class InMemoryCredentialRepository:
    def __init__(self):
        self._credentials: dict[str, Credential] = {}
        self._revoked: set[str] = set()
        self._lock = threading.Lock()

    def add(self, credential: Credential) -> None:
        with self._lock:
            self._credentials[credential.credential_id] = credential

    def get(self, credential_id: str) -> Credential | None:
        with self._lock:
            return self._credentials.get(credential_id)

    def list_all(self) -> list[Credential]:
        with self._lock:
            return list(self._credentials.values())

    def revoke(self, credential_id: str) -> None:
        with self._lock:
            self._revoked.add(credential_id)

    def is_revoked(self, credential_id: str) -> bool:
        with self._lock:
            return credential_id in self._revoked


class InMemoryProofRepository:
    def __init__(self):
        self._proofs: dict[str, Proof] = {}
        self._lock = threading.Lock()

    def add(self, proof: Proof) -> None:
        with self._lock:
            self._proofs[proof.code] = proof

    def get_by_code(self, code: str) -> Proof | None:
        with self._lock:
            return self._proofs.get(code)

    def mark_used(self, code: str) -> bool:
        with self._lock:
            proof = self._proofs.get(code)
            if proof is None or proof.used:
                return False
            proof.used = True
            return True


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)
