# domain 계층: 외부 의존성 없는 순수 모델.
#
# "역방향 신원확인" POC — 지금은 국민만 기관에 신분을 증명하지만, 이 모델은 반대로
# 전화를 건 기관 직원/방문자가 "재직 자격증명"으로 먼저 자신을 증명하는 구조를 모사한다.
# 실제 모바일신분증 시스템과 연동하지 않는 시제품이다 — 발급 기관은 전부 "○○은행(모의)"
# 처럼 가상 기관이고(validate_mock_institution_name 참고), 서명 키도 이 프로세스가
# 기동 시 메모리에서 생성한 모의 키다(infrastructure/adapters/ed25519_issuer_signer.py 참고).
#
# 발급과 검증의 분리: 기관(Issuer)마다 다른 키쌍을 갖고, 자격증명에는 발급 기관의 issuer_id가
# 서명 대상으로 함께 들어간다. 검증 측은 개인키를 모르고 공개키 레지스트리에서 issuer_id로
# 공개키만 조회해 서명을 확인한다(domain/ports.py 참고).

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

# 가상 기관임을 표시하는 접미사. 실제 기관명만 단독으로 쓰면 실제 기관이 발급한 것처럼
# 보일 수 있어서, 발급 단계에서 이 표시가 없는 기관명은 거부한다.
MOCK_INSTITUTION_MARK = "(모의)"


class VerificationReason(str, Enum):
    """N-04 설명가능성: 검증 결과마다 "왜 그렇게 판정했는가"를 사유 코드로 남긴다.
    국민용 화면은 확인됨/확인 불가 두 가지만 보여주지만, API 응답과 메트릭
    (vps_verify_requests_total{reason})에는 이 코드가 그대로 남는다."""

    VERIFIED = "verified"
    CODE_NOT_FOUND = "code_not_found"  # 사칭범: 애초에 발급된 증명이 없음
    ISSUER_UNKNOWN = "issuer_unknown"  # 공개키 레지스트리에 없는 기관이 발급했다고 주장
    SIGNATURE_INVALID = "signature_invalid"  # 자격증명 위·변조
    CREDENTIAL_REVOKED = "credential_revoked"  # 퇴사자: 자격증명이 폐기됨
    PROOF_EXPIRED = "proof_expired"  # 일회용 증명의 유효시간 경과
    PROOF_ALREADY_USED = "proof_already_used"  # 같은 코드 재사용
    RATE_LIMITED = "rate_limited"  # 짧은 시간에 너무 많이 틀림(무차별 대입 의심) — domain/rate_limit.py


# 사람이 읽을 문구(N-04). 국민용 화면에는 노출하지 않고 API 응답/감사용으로만 쓴다.
REASON_MESSAGES: dict[VerificationReason, str] = {
    VerificationReason.VERIFIED: "기관(모의)이 서명한 재직 자격증명과 일회용 증명이 모두 유효합니다.",
    VerificationReason.CODE_NOT_FOUND: "입력한 코드로 발급된 증명이 없습니다. 상대방이 기관 직원임을 증명하지 못했습니다.",
    VerificationReason.ISSUER_UNKNOWN: "자격증명을 발급한 기관이 공개키 레지스트리에 등록되어 있지 않습니다(출처 불명).",
    VerificationReason.SIGNATURE_INVALID: "자격증명의 기관 서명이 일치하지 않습니다(위·변조 의심).",
    VerificationReason.CREDENTIAL_REVOKED: "자격증명이 폐기되었습니다(퇴사 등으로 더 이상 재직 중이 아님).",
    VerificationReason.PROOF_EXPIRED: "증명 유효시간이 지났습니다. 상대방에게 새 증명을 요청하세요.",
    VerificationReason.PROOF_ALREADY_USED: "이미 한 번 사용된 증명입니다(재사용 시도 의심).",
    VerificationReason.RATE_LIMITED: "짧은 시간에 확인 코드를 너무 여러 번 틀렸습니다(무차별 대입 의심). 검증하지 않고 거절했습니다.",
}


class CredentialNotFoundError(Exception):
    pass


class CredentialRevokedError(Exception):
    pass


class IssuerNotFoundError(Exception):
    pass


def validate_mock_institution_name(institution_name: str) -> None:
    if MOCK_INSTITUTION_MARK not in institution_name:
        raise ValueError(
            f"기관명에 '{MOCK_INSTITUTION_MARK}' 표시가 필요합니다(예: ○○은행{MOCK_INSTITUTION_MARK}) — "
            "이 POC는 실제 기관과 연동하지 않는 모의 시제품입니다."
        )


def mask_staff_name(name: str) -> str:
    """국민용 화면에는 성명 일부만 보인다: "김민수" -> "김○○"."""
    name = name.strip()
    if len(name) <= 1:
        return "○"
    return name[0] + "○" * (len(name) - 1)


@dataclass(frozen=True)
class Issuer:
    """자격증명을 발급하는 모의 기관. 기관마다 서로 다른 키쌍을 갖는다(개인키는 발급 측
    어댑터만, 공개키는 레지스트리가 갖는다). 실제 기관으로 보이지 않게 기관명에 "(모의)"가
    없으면 만들 수 없다."""

    issuer_id: str
    institution_name: str

    def __post_init__(self):
        validate_mock_institution_name(self.institution_name)


@dataclass(frozen=True)
class Credential:
    """모의 기관이 서명해 발급한 재직 자격증명.

    폐기 여부는 이 객체에 넣지 않는다 — 서명된 자격증명 자체는 불변이고, 폐기는 별도
    폐기 목록(CredentialRepositoryPort.revoke/is_revoked)으로 관리한다. 실제 PKI의
    인증서와 CRL을 분리하는 방식과 같은 이유다(폐기할 때 서명을 다시 할 필요가 없음).
    """

    credential_id: str
    issuer_id: str
    institution_name: str
    staff_display_name: str
    role: str
    issued_at: datetime
    signature: bytes = b""

    def signing_payload(self) -> bytes:
        """서명 대상 바이트. 키 순서를 고정한 JSON이라 같은 내용이면 항상 같은 바이트가
        나온다 — 필드 하나라도 바뀌면(이름 변조, 발급 기관 바꿔치기 등) 서명 검증이 실패한다."""
        return json.dumps(
            {
                "credential_id": self.credential_id,
                "issuer_id": self.issuer_id,
                "institution_name": self.institution_name,
                "staff_display_name": self.staff_display_name,
                "role": self.role,
                "issued_at": self.issued_at.isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")


@dataclass
class Proof:
    """직원이 통화/방문 중에 생성하는 일회용 증명. 국민은 6자리 code만 입력한다."""

    code: str
    credential_id: str
    purpose: str
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True)
class VerificationResult:
    """국민이 코드를 넣었을 때의 결과. verified=True일 때만 표시용 필드(기관명, 마스킹된
    성명, 목적, 만료시각)를 채운다 — 그 밖의 정보(credential_id, 역할, 서명 등)는 국민에게
    내보내지 않는다."""

    verified: bool
    reason: VerificationReason
    message: str
    institution_name: str | None = None
    staff_display_name_masked: str | None = None
    purpose: str | None = None
    expires_at: datetime | None = None

    @classmethod
    def unverified(cls, reason: VerificationReason) -> "VerificationResult":
        return cls(verified=False, reason=reason, message=REASON_MESSAGES[reason])
