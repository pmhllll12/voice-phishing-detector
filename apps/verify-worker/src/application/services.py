# application 계층: 역방향 신원확인 POC의 유스케이스(발급/증명 생성/검증/폐기).
# 실제 서명/저장은 infrastructure의 어댑터가 구현하고, 여기서는 domain/ports.py의
# 인터페이스로만 의존한다.

import secrets
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

from src.domain.entities import (
    REASON_MESSAGES,
    Credential,
    CredentialNotFoundError,
    CredentialRevokedError,
    IssuerNotFoundError,
    Proof,
    VerificationReason,
    VerificationResult,
    mask_staff_name,
)
from src.domain.ports import (
    ClockPort,
    CredentialRepositoryPort,
    IssuerPublicKeyRegistryPort,
    IssuerSigningPort,
    ProofRepositoryPort,
    SignatureVerifierPort,
)


def _random_six_digit_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


class IssueCredentialService:
    """모의 기관이 직원에게 재직 자격증명을 서명해 발급한다. 발급 측이라 개인키 서명 포트를
    쓴다. 기관명은 요청에서 받지 않고 레지스트리의 기관 정보에서 가져온다 — 등록된 기관만
    발급할 수 있다."""

    def __init__(
        self,
        signer: IssuerSigningPort,
        issuers: IssuerPublicKeyRegistryPort,
        credentials: CredentialRepositoryPort,
        clock: ClockPort,
    ):
        self._signer = signer
        self._issuers = issuers
        self._credentials = credentials
        self._clock = clock

    def execute(
        self, issuer_id: str, staff_display_name: str, role: str, credential_id: str | None = None
    ) -> Credential:
        """credential_id는 시연용 고정 ID(기동 시 시드)에만 쓴다 — 평소엔 비워서 uuid를 받는다."""
        issuer = self._issuers.get_issuer(issuer_id)
        if issuer is None:
            raise IssuerNotFoundError(issuer_id)
        unsigned = Credential(
            credential_id=credential_id or str(uuid.uuid4()),
            issuer_id=issuer.issuer_id,
            institution_name=issuer.institution_name,
            staff_display_name=staff_display_name,
            role=role,
            issued_at=self._clock.now(),
        )
        signature = self._signer.sign(issuer.issuer_id, unsigned.signing_payload())
        credential = replace(unsigned, signature=signature)
        self._credentials.add(credential)
        return credential


class RevokeCredentialService:
    """퇴사자 시나리오: 자격증명을 폐기 목록에 올린다. 이미 생성해둔 증명도 이후 검증에서
    전부 credential_revoked로 떨어진다(증명이 자격증명을 참조만 하기 때문)."""

    def __init__(self, credentials: CredentialRepositoryPort):
        self._credentials = credentials

    def execute(self, credential_id: str) -> None:
        if self._credentials.get(credential_id) is None:
            raise CredentialNotFoundError(credential_id)
        self._credentials.revoke(credential_id)


class CreateProofService:
    """직원이 통화/방문 중에 일회용 증명(6자리 코드)을 생성한다."""

    # 6자리 코드가 이미 쓰이는 중인 코드와 겹치면 다시 뽑는다. 10^6 공간에서 시연 규모로는
    # 거의 안 겹치지만, 겹치면 다른 사람의 증명을 덮어쓰게 되므로 막아둔다.
    _MAX_CODE_ATTEMPTS = 10

    def __init__(
        self,
        credentials: CredentialRepositoryPort,
        proofs: ProofRepositoryPort,
        clock: ClockPort,
        ttl_seconds: int,
        code_generator: Callable[[], str] = _random_six_digit_code,
    ):
        self._credentials = credentials
        self._proofs = proofs
        self._clock = clock
        self._ttl = timedelta(seconds=ttl_seconds)
        self._code_generator = code_generator

    def execute(self, credential_id: str, purpose: str) -> Proof:
        if self._credentials.get(credential_id) is None:
            raise CredentialNotFoundError(credential_id)
        if self._credentials.is_revoked(credential_id):
            raise CredentialRevokedError(credential_id)

        for _ in range(self._MAX_CODE_ATTEMPTS):
            code = self._code_generator()
            if self._proofs.get_by_code(code) is None:
                break
        else:
            raise RuntimeError("증명 코드 생성 실패: 사용 가능한 코드를 찾지 못했습니다.")

        proof = Proof(
            code=code,
            credential_id=credential_id,
            purpose=purpose,
            expires_at=self._clock.now() + self._ttl,
        )
        self._proofs.add(proof)
        return proof


class VerifyProofService:
    """국민이 입력한 코드를 검증한다. 실패 사유는 전부 verified=False로 모이고, 사유 코드만
    다르게 남는다(N-04).

    판정 순서: 코드 없음 → 발급 기관 불명 → 서명 불일치 → 폐기 → 만료 → 이미 사용됨. 서명을 폐기/만료보다
    먼저 보는 이유는, 위·변조된 자격증명이라면 "폐기됨"이나 "만료됨" 같은 다른 사유로
    가려지지 않고 가장 심각한 사유로 기록돼야 하기 때문이다. 사용 처리(mark_used)는 모든
    검사를 통과한 뒤 마지막에 한다 — 실패한 검증 시도가 정상 증명을 소모하지 않게.

    개인키 서명 포트(IssuerSigningPort)는 받지 않는다. 자격증명의 issuer_id로 레지스트리에서
    공개키만 조회해 검증한다 — 실제 구조에서 검증 측이 발급 기관의 개인키를 가질 일이 없는 것과
    같다. 레지스트리에 없는 기관이면 서명을 볼 공개키가 없으므로 issuer_unknown이다.
    """

    def __init__(
        self,
        issuers: IssuerPublicKeyRegistryPort,
        verifier: SignatureVerifierPort,
        credentials: CredentialRepositoryPort,
        proofs: ProofRepositoryPort,
        clock: ClockPort,
    ):
        self._issuers = issuers
        self._verifier = verifier
        self._credentials = credentials
        self._proofs = proofs
        self._clock = clock

    def execute(self, code: str) -> VerificationResult:
        proof = self._proofs.get_by_code(code.strip())
        if proof is None:
            return VerificationResult.unverified(VerificationReason.CODE_NOT_FOUND)

        # 증명이 가리키는 자격증명이 아예 없으면 서명을 검증할 대상도 없으므로 서명 불일치와
        # 같은 사유로 본다(정상 경로에서는 생기지 않는 상태 — 저장소 손상/조작 시에만).
        credential = self._credentials.get(proof.credential_id)
        if credential is None:
            return VerificationResult.unverified(VerificationReason.SIGNATURE_INVALID)

        public_key = self._issuers.get_public_key(credential.issuer_id)
        if public_key is None:
            return VerificationResult.unverified(VerificationReason.ISSUER_UNKNOWN)

        if not self._verifier.verify(public_key, credential.signing_payload(), credential.signature):
            return VerificationResult.unverified(VerificationReason.SIGNATURE_INVALID)

        if self._credentials.is_revoked(credential.credential_id):
            return VerificationResult.unverified(VerificationReason.CREDENTIAL_REVOKED)

        if self._clock.now() >= proof.expires_at:
            return VerificationResult.unverified(VerificationReason.PROOF_EXPIRED)

        if not self._proofs.mark_used(proof.code):
            return VerificationResult.unverified(VerificationReason.PROOF_ALREADY_USED)

        return VerificationResult(
            verified=True,
            reason=VerificationReason.VERIFIED,
            message=REASON_MESSAGES[VerificationReason.VERIFIED],
            institution_name=credential.institution_name,
            staff_display_name_masked=mask_staff_name(credential.staff_display_name),
            purpose=proof.purpose,
            expires_at=proof.expires_at,
        )
