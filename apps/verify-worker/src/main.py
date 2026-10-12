# apps/verify-worker 진입점 — "역방향 신원확인" POC(모의 재직 자격증명 발급/검증) API.
#
# 이 서비스는 실제 모바일신분증 시스템과 연동하지 않는, 구조만 모사한 시제품이다.
# 발급 기관은 전부 "○○은행(모의)" 같은 가상 기관이고, 서명 키는 기동 시 메모리에서
# 만든 모의 키다(infrastructure/adapters/ed25519_issuer_signer.py 참고).
#
# 헥사고날 계층 구성: domain(Credential/Proof/VerificationResult, 포트 인터페이스)
# -> application(발급/증명 생성/검증/폐기 유스케이스) -> infrastructure(인메모리 저장소,
# Ed25519 발급 서명/검증 어댑터, 공개키 레지스트리, 이 FastAPI 진입점).
#
# 발급과 검증의 분리: 모의 기관(MOCK_ISSUERS)마다 키쌍을 따로 만들고, 개인키는 발급 서명
# 어댑터만, 공개키는 레지스트리만 갖는다. 발급 유스케이스는 서명 어댑터를, 검증 유스케이스는
# 레지스트리 + 공개키 검증기만 받는다(아래 조립 참고). 레지스트리는 GET /api/v1/issuers로
# 공개한다. 한 프로세스 안에서 나눈 것이라 "물리적" 분리는 아니다(docs/poc-mobile-id.md 5장).
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

import ipaddress
import logging
import os
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from src.application.services import (
    CreateProofService,
    IssueCredentialService,
    RateLimitedVerifyService,
    RevokeCredentialService,
    VerifyProofService,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from src.domain.entities import (
    Credential,
    CredentialNotFoundError,
    CredentialRevokedError,
    Issuer,
    IssuerNotFoundError,
    VerificationReason,
    VerificationResult,
)
from src.domain.rate_limit import RateLimitPolicy
from src.infrastructure.adapters.ed25519_issuer_signer import Ed25519IssuerSigner
from src.infrastructure.adapters.ed25519_verifier import Ed25519SignatureVerifier
from src.infrastructure.adapters.in_memory_attempt_store import InMemoryFailedAttemptStore
from src.infrastructure.adapters.in_memory_issuer_registry import InMemoryIssuerPublicKeyRegistry
from src.infrastructure.adapters.in_memory_repository import (
    InMemoryCredentialRepository,
    InMemoryProofRepository,
    SystemClock,
)
from src.infrastructure.metrics import (
    credentials_revoked_total,
    proofs_created_total,
    rate_limited_total,
    verify_duration_seconds,
    verify_requests_total,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# 일회용 증명 유효시간. 통화 중에 국민이 코드를 받아 입력하기까지 충분하면서도, 코드가
# 유출돼도 오래 쓰이지 않을 정도로 짧게 — 기본 3분.
PROOF_TTL_SECONDS = int(os.environ.get("PROOF_TTL_SECONDS", "180"))

# 확인 코드 무차별 대입 방어(domain/rate_limit.py): 클라이언트(IP)별로 이 시간 안에 이만큼 틀리면
# 다음 시도부터 429. apps/api도 같은 이름의 환경변수로 같은 규칙을 건다.
RATE_LIMIT_POLICY = RateLimitPolicy(
    max_failures=int(os.environ.get("VERIFY_RATE_LIMIT_MAX_FAILURES", "5")),
    window_seconds=int(os.environ.get("VERIFY_RATE_LIMIT_WINDOW_SECONDS", "600")),
)

# 국민 검증은 apps/api를 거쳐 들어오므로, 그대로 두면 모든 국민이 api의 IP 하나로 보여 실패
# 횟수를 함께 쓰게 된다. 그래서 이 목록의 주소(=api가 떠 있는 곳)에서 온 요청에 한해서만
# X-Forwarded-For의 클라이언트 IP를 믿는다. 아무 데서나 온 X-Forwarded-For를 믿으면 헤더만
# 바꿔 제한을 우회할 수 있다.
TRUSTED_PROXIES = {
    p.strip() for p in os.environ.get("VERIFY_TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()
}

MOCK_NOTICE = "모의 시연용 시제품이며 실제 모바일신분증과 연동되지 않습니다."

app = FastAPI(title="Voice Phishing Detector — Verify Worker (모의 시제품)", description=MOCK_NOTICE)

# apps/api와 같은 이유(WSL2에서 브라우저 origin이 매번 달라짐)로 로컬 개발 중에는 전부 허용.
# 직원용 화면(/verify/staff)이 이 서비스를 직접 호출한다.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 모의 발급 기관. 기관마다 서로 다른 Ed25519 키쌍을 기동 시 만든다 — 전부 가상 기관이다.
MOCK_ISSUERS = [
    Issuer("mock-bank", "○○은행(모의)"),
    Issuer("mock-district", "△△구청(모의)"),
    Issuer("mock-gas", "□□도시가스(모의)"),
]

_issuer_signer = Ed25519IssuerSigner()  # 발급 측: 개인키
_issuer_registry = InMemoryIssuerPublicKeyRegistry()  # 검증 측: 공개키만
for _issuer in MOCK_ISSUERS:
    _issuer_registry.register(_issuer, _issuer_signer.create_key(_issuer.issuer_id))

_credentials = InMemoryCredentialRepository()
_proofs = InMemoryProofRepository()
_clock = SystemClock()

issue_credential_service = IssueCredentialService(_issuer_signer, _issuer_registry, _credentials, _clock)
revoke_credential_service = RevokeCredentialService(_credentials)
create_proof_service = CreateProofService(_credentials, _proofs, _clock, ttl_seconds=PROOF_TTL_SECONDS)
verify_proof_service = VerifyProofService(
    _issuer_registry, Ed25519SignatureVerifier(), _credentials, _proofs, _clock
)
rate_limited_verify_service = RateLimitedVerifyService(
    verify_proof_service, InMemoryFailedAttemptStore(), _clock, RATE_LIMIT_POLICY
)

# 시연용 고정 자격증명 3건(전화 2 + 방문 1). 직원용 화면이 바로 고를 수 있게 기동 시 발급해둔다
# — 이름도 기관도 전부 가상이다. 퇴사자 시나리오는 이 둘을 폐기하지 말고 새로 발급해서 시연할 것
# (README "역방향 신원확인 POC" 시연 순서 참고).
DEMO_CREDENTIALS = [
    ("demo-bank-staff", "mock-bank", "김민수", "대출상담 직원"),
    ("demo-district-staff", "mock-district", "이영희", "복지 담당 주무관"),
    ("demo-gas-staff", "mock-gas", "박준호", "안전점검원"),  # 방문 시나리오(QR)
]
for _cid, _issuer_id, _name, _role in DEMO_CREDENTIALS:
    issue_credential_service.execute(_issuer_id, _name, _role, credential_id=_cid)


def _serialize_credential(credential: Credential) -> dict:
    """기관/직원 측 응답. 서명은 시연에서 "실제로 서명됐다"를 보여주기 위해 hex로 내보낸다
    (서명은 비밀이 아니다). 국민용 검증 응답에는 이 함수를 쓰지 않는다."""
    return {
        "credential_id": credential.credential_id,
        "issuer_id": credential.issuer_id,
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


def _client_key(request: Request) -> str:
    """실패 횟수를 셀 클라이언트 IP. 직접 연결한 쪽이 신뢰 프록시(api)일 때만 X-Forwarded-For를
    오른쪽부터 보며 신뢰 프록시가 아닌 첫 주소를 쓴다(그 왼쪽은 클라이언트가 마음대로 넣을 수
    있는 값이라 믿지 않는다)."""
    peer = request.client.host if request.client else "unknown"
    if peer not in TRUSTED_PROXIES:
        return peer
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(forwarded):
        if hop in TRUSTED_PROXIES:
            continue
        try:
            ipaddress.ip_address(hop)
        except ValueError:
            break
        return hop
    return peer


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "proof_ttl_seconds": PROOF_TTL_SECONDS,
        "rate_limit": {
            "max_failures": RATE_LIMIT_POLICY.max_failures,
            "window_seconds": RATE_LIMIT_POLICY.window_seconds,
        },
        "notice": MOCK_NOTICE,
    }


@app.get("/metrics")
async def metrics_endpoint() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _serialize_issuer(issuer: Issuer) -> dict:
    """공개키 레지스트리 항목. 공개키는 비밀이 아니므로 그대로 공개한다 — raw(hex)와 PEM 둘 다
    준다. 모의 기관의 모의 키라는 고지를 응답마다 붙인다."""
    raw = _issuer_registry.get_public_key(issuer.issuer_id) or b""
    pem = Ed25519PublicKey.from_public_bytes(raw).public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    return {
        "issuer_id": issuer.issuer_id,
        "institution_name": issuer.institution_name,
        "algorithm": "Ed25519",
        "public_key_hex": raw.hex(),
        "public_key_pem": pem.decode("ascii"),
        "notice": MOCK_NOTICE,
    }


@app.get("/api/v1/issuers")
async def list_issuers() -> dict:
    """공개키 레지스트리: 등록된 모의 발급 기관과 각 공개키. 검증 측이 조회하는 정보다."""
    return {"issuers": [_serialize_issuer(i) for i in _issuer_registry.list_issuers()]}


@app.get("/api/v1/issuers/{issuer_id}/public-key")
async def get_issuer_public_key(issuer_id: str) -> dict:
    issuer = _issuer_registry.get_issuer(issuer_id)
    if issuer is None:
        raise HTTPException(status_code=404, detail=f"등록되지 않은 발급 기관입니다: {issuer_id}")
    return _serialize_issuer(issuer)


class IssueCredentialRequest(BaseModel):
    # issuer_id(권장) 또는 institution_name(기존 호출 호환) 중 하나. institution_name만 오면
    # 등록된 모의 기관 중 같은 이름을 찾아 쓴다.
    issuer_id: str | None = Field(default=None, max_length=50)
    institution_name: str | None = Field(default=None, min_length=1, max_length=50)
    staff_display_name: str = Field(min_length=1, max_length=30)
    role: str = Field(min_length=1, max_length=50)


def _resolve_issuer_id(req: IssueCredentialRequest) -> str:
    if req.issuer_id:
        return req.issuer_id
    if req.institution_name:
        for issuer in _issuer_registry.list_issuers():
            if issuer.institution_name == req.institution_name:
                return issuer.issuer_id
    registered = ", ".join(f"{i.issuer_id}({i.institution_name})" for i in _issuer_registry.list_issuers())
    raise HTTPException(
        status_code=422,
        detail=f"등록된 모의 발급 기관이 아닙니다. issuer_id 또는 기관명으로 다음 중 하나를 지정하세요: {registered}",
    )


@app.post("/api/v1/credentials")
async def issue_credential(req: IssueCredentialRequest) -> dict:
    """모의 기관이 직원에게 재직 자격증명을 서명해 발급한다. 등록된 모의 기관(GET /api/v1/issuers)만
    발급할 수 있고, 그 밖의 기관(예: "(모의)" 표시 없는 기관명)은 422."""
    try:
        credential = issue_credential_service.execute(_resolve_issuer_id(req), req.staff_display_name, req.role)
    except IssuerNotFoundError as e:
        raise HTTPException(status_code=422, detail=f"등록되지 않은 발급 기관입니다: {e}") from e
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


@app.post("/api/v1/verify", response_model=None)
async def verify(req: VerifyRequest, request: Request) -> dict | JSONResponse:
    """국민이 코드를 넣어 검증한다. 검증 실패는 200 + verified=false로 응답한다 — "확인 불가"는
    오류가 아니라 정상적인 판정 결과다. 단 클라이언트별 실패 한도(RATE_LIMIT_POLICY)를 넘으면
    검증하지 않고 429 + reason=rate_limited(본문 형식은 같음)로 거절한다."""
    started_at = time.perf_counter()
    result = rate_limited_verify_service.execute(_client_key(request), req.code)
    verify_requests_total.labels(
        result="verified" if result.verified else "unverified", reason=result.reason.value
    ).inc()
    if result.reason == VerificationReason.RATE_LIMITED:
        rate_limited_total.inc()
        return JSONResponse(status_code=429, content=_serialize_verification(result))
    verify_duration_seconds.observe(time.perf_counter() - started_at)
    return _serialize_verification(result)


# TODO: 실패 횟수 기록(InMemoryFailedAttemptStore)은 프로세스 메모리라 워커/인스턴스를 늘리면
#       공유되지 않는다 — 여러 대로 늘릴 때는 같은 포트(FailedAttemptStorePort)의 Redis 구현이 필요.
