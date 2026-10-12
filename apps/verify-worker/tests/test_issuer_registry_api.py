# 공개키 레지스트리 엔드포인트(GET /api/v1/issuers, /issuers/{id}/public-key)가 공개키만
# 내보내는지 고정한다. httpx(TestClient)를 새 의존성으로 들이지 않으려고 엔드포인트 함수를
# 직접 호출한다(test_verify_response.py와 같은 이유로 main.py import가 가볍다).

import asyncio

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from fastapi import HTTPException

from src.main import IssueCredentialRequest, MOCK_ISSUERS, get_issuer_public_key, issue_credential, list_issuers


def test_list_issuers_exposes_public_keys_only():
    payload = asyncio.run(list_issuers())

    assert [i["issuer_id"] for i in payload["issuers"]] == [i.issuer_id for i in MOCK_ISSUERS]
    for issuer in payload["issuers"]:
        assert set(issuer) == {
            "issuer_id", "institution_name", "algorithm", "public_key_hex", "public_key_pem", "notice",
        }
        assert "(모의)" in issuer["institution_name"]
        assert len(bytes.fromhex(issuer["public_key_hex"])) == 32
        assert "PRIVATE" not in issuer["public_key_pem"]


def test_public_key_pem_matches_raw_key():
    issuer = asyncio.run(get_issuer_public_key("mock-bank"))

    pem_key = load_pem_public_key(issuer["public_key_pem"].encode("ascii"))
    assert pem_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex() == issuer["public_key_hex"]


def test_unknown_issuer_public_key_is_404():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_issuer_public_key("mock-unknown"))
    assert exc.value.status_code == 404


def test_issue_by_institution_name_still_works():
    """기존 호출(기관명으로 발급, demo_scenarios.sh 시나리오 3)은 등록된 기관으로 이어진다."""
    req = IssueCredentialRequest(institution_name="○○은행(모의)", staff_display_name="최퇴사", role="대출상담 직원")

    credential = asyncio.run(issue_credential(req))

    assert credential["issuer_id"] == "mock-bank"
    assert credential["institution_name"] == "○○은행(모의)"


@pytest.mark.parametrize(
    "req",
    [
        IssueCredentialRequest(institution_name="○○은행", staff_display_name="김민수", role="대출상담 직원"),
        IssueCredentialRequest(issuer_id="mock-unknown", staff_display_name="김민수", role="대출상담 직원"),
    ],
)
def test_issue_rejects_unregistered_issuer_with_422(req):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(issue_credential(req))
    assert exc.value.status_code == 422
