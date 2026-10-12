# 역방향 신원확인 POC의 시연 시나리오를 그대로 고정한 테스트.
# main.py가 아니라 application 계층을 직접 조립해서 검증한다 — 시간(만료)을 앞으로
# 돌리려면 ClockPort를 가짜로 바꿔 끼워야 하고, main.py의 전역 서비스는 실제 시계를 쓴다.
# 서명은 가짜가 아니라 실제 Ed25519 어댑터를 그대로 쓴다(서명 변조 테스트의 의미가 있도록).
#
# 시연 시나리오(README "역방향 신원확인 POC" 참고):
#   1. 정상 직원: 유효한 자격증명 → 증명 생성 → 검증 → verified
#   2. 사칭범: 존재하지 않는 코드 → unverified
#   3. 퇴사자: 자격증명 폐기 후, 폐기 전에 생성했던 증명으로 검증 → unverified
# 추가: 만료, 재사용, 서명 변조 각각 unverified.

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from src.application.services import (
    CreateProofService,
    IssueCredentialService,
    RevokeCredentialService,
    VerifyProofService,
)
from src.domain.entities import CredentialRevokedError, VerificationReason, mask_staff_name
from src.infrastructure.adapters.ed25519_signer import Ed25519CredentialSigner
from src.infrastructure.adapters.in_memory_repository import InMemoryCredentialRepository, InMemoryProofRepository

TTL_SECONDS = 180


class _FakeClock:
    def __init__(self):
        self.current = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class _System:
    """main.py와 같은 조립을 시계만 가짜로 바꿔 재현한다."""

    def __init__(self):
        self.clock = _FakeClock()
        self.signer = Ed25519CredentialSigner()
        self.credentials = InMemoryCredentialRepository()
        self.proofs = InMemoryProofRepository()
        self.issue = IssueCredentialService(self.signer, self.credentials, self.clock)
        self.revoke = RevokeCredentialService(self.credentials)
        self.create_proof = CreateProofService(self.credentials, self.proofs, self.clock, ttl_seconds=TTL_SECONDS)
        self.verify = VerifyProofService(self.signer, self.credentials, self.proofs, self.clock)


@pytest.fixture
def system() -> _System:
    return _System()


def _issue_bank_staff(system: _System):
    return system.issue.execute("○○은행(모의)", "김민수", "대출상담 직원")


def test_scenario1_genuine_staff_is_verified(system):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")

    result = system.verify.execute(proof.code)

    assert result.verified is True
    assert result.reason == VerificationReason.VERIFIED
    assert result.institution_name == "○○은행(모의)"
    assert result.staff_display_name_masked == "김○○"
    assert result.purpose == "대출 상담 전화"
    assert result.expires_at == system.clock.now() + timedelta(seconds=TTL_SECONDS)
    assert len(proof.code) == 6 and proof.code.isdigit()


def test_scenario2_impersonator_with_unknown_code_is_unverified(system):
    _issue_bank_staff(system)

    result = system.verify.execute("123456")

    assert result.verified is False
    assert result.reason == VerificationReason.CODE_NOT_FOUND
    assert result.message  # N-04: 사람이 읽을 사유 문구가 반드시 붙는다
    assert result.institution_name is None and result.staff_display_name_masked is None


def test_scenario3_resigned_staff_proof_is_unverified_after_revocation(system):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "방문 상담")

    system.revoke.execute(credential.credential_id)
    result = system.verify.execute(proof.code)

    assert result.verified is False
    assert result.reason == VerificationReason.CREDENTIAL_REVOKED
    # 폐기 이후에는 새 증명도 만들 수 없다
    with pytest.raises(CredentialRevokedError):
        system.create_proof.execute(credential.credential_id, "방문 상담")


def test_expired_proof_is_unverified(system):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")

    system.clock.advance(TTL_SECONDS)
    result = system.verify.execute(proof.code)

    assert result.verified is False
    assert result.reason == VerificationReason.PROOF_EXPIRED


def test_reused_proof_is_unverified(system):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")

    first = system.verify.execute(proof.code)
    second = system.verify.execute(proof.code)

    assert first.verified is True
    assert second.verified is False
    assert second.reason == VerificationReason.PROOF_ALREADY_USED


def test_tampered_credential_signature_is_unverified(system):
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")

    # 저장된 자격증명의 이름만 바꾸고 서명은 그대로 둔다(위·변조).
    system.credentials.add(replace(credential, staff_display_name="박사칭"))
    result = system.verify.execute(proof.code)

    assert result.verified is False
    assert result.reason == VerificationReason.SIGNATURE_INVALID


def test_failed_verification_does_not_consume_proof(system):
    """만료 직전에 다른 사유로 실패한 시도가 정상 증명을 소모하면 안 된다 — 판정 순서상
    mark_used는 모든 검사를 통과한 뒤에만 호출된다(VerifyProofService 상단 주석 참고)."""
    credential = _issue_bank_staff(system)
    proof = system.create_proof.execute(credential.credential_id, "대출 상담 전화")

    system.verify.execute("000000" if proof.code != "000000" else "111111")
    result = system.verify.execute(proof.code)

    assert result.verified is True


def test_issue_rejects_institution_without_mock_mark(system):
    with pytest.raises(ValueError):
        system.issue.execute("○○은행", "김민수", "대출상담 직원")


@pytest.mark.parametrize(("name", "masked"), [("김민수", "김○○"), ("남궁민수", "남○○○"), ("이", "○")])
def test_mask_staff_name(name, masked):
    assert mask_staff_name(name) == masked
