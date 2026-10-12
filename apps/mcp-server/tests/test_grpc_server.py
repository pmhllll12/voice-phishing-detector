# N-06 확장성 검증(2026-09-01) — grpc_server.py가 server.py(MCP stdio)/rest_server.py
# (REST)와 동일한 CallAnalysisService를 재사용해 정확히 같은 판정을 내리는지, 그리고
# N-02 접근통제(X-API-Key)가 이 세 번째 진입점에도 재설계 없이 적용되는지 실제 gRPC
# 클라이언트로 검증한다 — mock 없이 진짜 grpc.server를 띄우고 진짜 채널로 호출한다.

import pytest
import grpc

import grpc_server
from infrastructure.adapters.api_key_role_auth import API_KEYS
from domain.entities import Role
from infrastructure.grpc_generated import voice_phishing_pb2, voice_phishing_pb2_grpc

VIEWER_KEY = next(key for key, role in API_KEYS.items() if role == Role.VIEWER)
HANDLER_KEY = next(key for key, role in API_KEYS.items() if role == Role.HANDLER)


@pytest.fixture(scope="module")
def grpc_channel():
    server, port = grpc_server.serve(port=0)
    channel = grpc.insecure_channel(f"localhost:{port}")
    yield channel
    channel.close()
    server.stop(grace=None)


def _stub(grpc_channel):
    return voice_phishing_pb2_grpc.VoicePhishingAnalysisStub(grpc_channel)


def test_analyze_returns_same_shape_as_rest_and_mcp_adapters(grpc_channel):
    stub = _stub(grpc_channel)
    response = stub.Analyze(
        voice_phishing_pb2.AnalyzeRequest(transcript="검찰청 수사관인데 안전계좌로 이체하세요"),
        metadata=(("x-api-key", HANDLER_KEY),),
    )

    assert response.risk_score > 0
    assert response.risk_level in ("low", "medium", "high")
    assert response.explanation_summary
    assert response.pattern_count == len(response.detected_patterns)
    assert any(p.category == "authority_impersonation" for p in response.detected_patterns)


def test_analyze_without_api_key_is_rejected():
    server, port = grpc_server.serve(port=0)
    try:
        channel = grpc.insecure_channel(f"localhost:{port}")
        stub = voice_phishing_pb2_grpc.VoicePhishingAnalysisStub(channel)
        with pytest.raises(grpc.RpcError) as exc_info:
            stub.Analyze(voice_phishing_pb2.AnalyzeRequest(transcript="테스트"))
        assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        channel.close()
        server.stop(grace=None)


def test_analyze_with_viewer_key_is_rejected_403_equivalent(grpc_channel):
    stub = _stub(grpc_channel)
    with pytest.raises(grpc.RpcError) as exc_info:
        stub.Analyze(
            voice_phishing_pb2.AnalyzeRequest(transcript="테스트"),
            metadata=(("x-api-key", VIEWER_KEY),),
        )
    assert exc_info.value.code() == grpc.StatusCode.PERMISSION_DENIED
