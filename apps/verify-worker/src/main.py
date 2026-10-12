# apps/verify-worker 진입점 — "역방향 신원확인" POC(모의 재직 자격증명 발급/검증) API.
#
# 이 서비스는 실제 모바일신분증 시스템과 연동하지 않는, 구조만 모사한 시제품이다.
# 발급 기관은 전부 "○○은행(모의)" 같은 가상 기관이고, 서명 키는 기동 시 메모리에서
# 만든 모의 키다(infrastructure/adapters/ed25519_signer.py 참고).
#
# 헥사고날 계층 구성: domain(Credential/Proof/VerificationResult, 포트 인터페이스)
# -> application(발급/증명 생성/검증/폐기 유스케이스) -> infrastructure(인메모리 저장소,
# Ed25519 서명 어댑터, 이 FastAPI 진입점).
#
# 흐름: 모의 기관이 직원에게 자격증명 발급(POST /credentials)
#   -> 직원이 통화/방문 중 일회용 증명 생성(POST /proofs, 6자리 코드)
#   -> 국민이 그 코드를 입력해 검증(POST /verify) — apps/api가 통화 기록에 결과를 붙일 때도
#      이 엔드포인트를 호출한다(apps/api POST /api/v1/calls/{call_id}/verification).
#
# 탐지(F-01)와의 관계: AI(apps/api의 verification_prompt)는 기관사칭을 "의심"만 하고,
# 상대가 실제 직원인지는 이 서비스의 서명 검증이 "확정"한다.
#
# N-02 RBAC은 걸지 않았다 — 직원용/국민용 시연 화면이 브라우저에서 직접 호출하는 POC라
# 로컬 시연 범위로 한정한다. 실제 구조라면 발급/폐기는 기관 인증이, 증명 생성은 직원 본인
# 인증이 필요하다(docs/poc-mobile-id.md "한계" 참고).

import logging
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from src.application.services import (
    CreateProofService,
    IssueCredentialService,
    RevokeCredentialService,
    VerifyProofService,
)
from src.domain.entities import Credential, CredentialNotFoundError, CredentialRevokedError, VerificationResult
from src.infrastructure.adapters.ed25519_signer import Ed25519CredentialSigner
from src.infrastructure.adapters.in_memory_repository import (
    InMemoryCredentialRepository,
    InMemoryProofRepository,
    SystemClock,
)
from src.infrastructure.metrics import (
    credentials_revoked_total,
    proofs_created_total,
    verify_duration_seconds,
    verify_requests_total,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# 일회용 증명 유효시간. 통화 중에 국민이 코드를 받아 입력하기까지 충분하면서도, 코드가
# 유출돼도 오래 쓰이지 않을 정도로 짧게 — 기본 3분.
PROOF_TTL_SECONDS = int(os.environ.get("PROOF_TTL_SECONDS", "180"))

MOCK_NOTICE = "모의 시연용 시제품이며 실제 모바일신분증과 연동되지 않습니다."

app = FastAPI(title="Voice Phishing Detector — Verify Worker (모의 시제품)", description=MOCK_NOTICE)

# apps/api와 같은 이유(WSL2에서 브라우저 origin이 매번 달라짐)로 로컬 개발 중에는 전부 허용.
# 직원용 화면(/verify/staff)이 이 서비스를 직접 호출한다.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_signer = Ed25519CredentialSigner()
_credentials = InMemoryCredentialRepository()
_proofs = InMemoryProofRepository()
_clock = SystemClock()

issue_credential_service = IssueCredentialService(_signer, _credentials, _clock)
revoke_credential_service = RevokeCredentialService(_credentials)
create_proof_service = CreateProofService(_credentials, _proofs, _clock, ttl_seconds=PROOF_TTL_SECONDS)
verify_proof_service = VerifyProofService(_signer, _credentials, _proofs, _clock)

# 시연용 고정 자격증명 2건. 직원용 화면이 바로 고를 수 있게 기동 시 발급해둔다 — 이름도
# 기관도 전부 가상이다. 퇴사자 시나리오는 이 둘을 폐기하지 말고 새로 발급해서 시연할 것
# (README "역방향 신원확인 POC" 시연 순서 참고).
DEMO_CREDENTIALS = [
    ("demo-bank-staff", "○○은행(모의)", "김민수", "대출상담 직원"),
    ("demo-district-staff", "△△구청(모의)", "이영희", "복지 담당 주무관"),
]
for _cid, _inst, _name, _role in DEMO_CREDENTIALS:
    issue_credential_service.execute(_inst, _name, _role, credential_id=_cid)


def _serialize_credential(credential: Credential) -> dict:
    """기관/직원 측 응답. 서명은 시연에서 "실제로 서명됐다"를 보여주기 위해 hex로 내보낸다
    (서명은 비밀이 아니다). 국민용 검증 응답에는 이 함수를 쓰지 않는다."""
    return {
        "credential_id": credential.credential_id,
        "institution_name": credential.institution_name,
        "staff_display_name": credential.staff_display_name,
        "role": credential.role,
        "issued_at": credential.issued_at.isoformat(),
        "signature": credential.signature.hex(),
        "revoked": _credentials.is_revoked(credential.credential_id),
    }


def _serialize_verification(result: VerificationResult) -> dict:
    """국민용 응답. verified=True일 때도 기관명/마스킹된 성명/목적/만료시각만 내보낸다 —
    credential_id, 역할, 서명 등은 의도적으로 뺀다."""
    payload = {"verified": result.verified, "reason": result.reason.value, "message": result.message}
    if result.verified:
        payload.update(
            {
                "institution_name": result.institution_name,
                "staff_display_name": result.staff_display_name_masked,
                "purpose": result.purpose,
                "expires_at": result.expires_at.isoformat() if result.expires_at else None,
            }
        )
    return payload


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "proof_ttl_seconds": PROOF_TTL_SECONDS, "notice": MOCK_NOTICE}


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


class IssueCredentialRequest(BaseModel):
    institution_name: str = Field(min_length=1, max_length=50)
    staff_display_name: str = Field(min_length=1, max_length=30)
    role: str = Field(min_length=1, max_length=50)


@app.post("/api/v1/credentials")
async def issue_credential(req: IssueCredentialRequest) -> dict:
    """모의 기관이 직원에게 재직 자격증명을 서명해 발급한다. 기관명에 "(모의)"가 없으면 422."""
    try:
        credential = issue_credential_service.execute(req.institution_name, req.staff_display_name, req.role)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _serialize_credential(credential)


@app.get("/api/v1/credentials")
async def list_credentials() -> dict:
    """직원용 화면의 "자격증명 선택" 목록."""
    return {"credentials": [_serialize_credential(c) for c in _credentials.list_all()]}


@app.post("/api/v1/credentials/{credential_id}/revoke")
async def revoke_credential(credential_id: str) -> dict:
    """퇴사자 시나리오: 폐기 이후에는 이미 생성해둔 증명도 검증에서 실패한다."""
    try:
        revoke_credential_service.execute(credential_id)
    except CredentialNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"자격증명을 찾을 수 없습니다: {credential_id}") from e
    credentials_revoked_total.inc()
    return {"credential_id": credential_id, "revoked": True}


class CreateProofRequest(BaseModel):
    credential_id: str
    purpose: str = Field(min_length=1, max_length=50)


@app.post("/api/v1/proofs")
async def create_proof(req: CreateProofRequest) -> dict:
    try:
        proof = create_proof_service.execute(req.credential_id, req.purpose)
    except CredentialNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"자격증명을 찾을 수 없습니다: {req.credential_id}") from e
    except CredentialRevokedError as e:
        raise HTTPException(status_code=409, detail="폐기된 자격증명으로는 증명을 생성할 수 없습니다.") from e
    proofs_created_total.inc()
    return {
        "code": proof.code,
        "purpose": proof.purpose,
        "expires_at": proof.expires_at.isoformat(),
        "ttl_seconds": PROOF_TTL_SECONDS,
    }


class VerifyRequest(BaseModel):
    code: str = Field(max_length=20)


@app.post("/api/v1/verify")
async def verify(req: VerifyRequest) -> dict:
    """국민이 코드를 넣어 검증한다. 어떤 실패든 200 + verified=false로 응답한다 — "확인 불가"는
    오류가 아니라 정상적인 판정 결과다."""
    started_at = time.perf_counter()
    result = verify_proof_service.execute(req.code)
    verify_duration_seconds.observe(time.perf_counter() - started_at)
    verify_requests_total.labels(
        result="verified" if result.verified else "unverified", reason=result.reason.value
    ).inc()
    return _serialize_verification(result)


# TODO: 실제 구조로 옮긴다면 (1) 검증 측이 개인키 없이 기관 공개키 레지스트리만 조회하도록
#       서명/검증 어댑터를 분리하고, (2) 증명 코드 무차별 대입(10^6 공간)에 대비해 검증
#       요청에 속도 제한을 걸 것 — 지금은 TTL(기본 180초)과 일회용 처리만으로 완화한다.
