# infrastructure 계층: Prometheus 클라이언트 연동.
# 다른 앱의 src/infrastructure/metrics.py와 같은 패턴(vps_ 접두사)을 따르고, 이 서비스는
# vps_verify_ 로 묶는다.

from prometheus_client import Counter, Histogram

# 국민이 코드를 넣어 검증한 횟수. reason은 domain/entities.py VerificationReason 값 —
# "확인 불가"가 늘었을 때 사칭(code_not_found)인지 퇴사자(credential_revoked)인지
# 재사용 시도(proof_already_used)인지 대시보드에서 바로 구분하기 위해 라벨로 둔다(N-04).
verify_requests_total = Counter(
    "vps_verify_requests_total",
    "Total number of proof verification requests",
    labelnames=["result", "reason"],  # result: "verified" | "unverified"
)

# 검증 1건(코드 조회 + Ed25519 서명 검증 + 폐기/만료/사용 확인)에 걸린 시간.
# 기본 버킷(5ms~)은 이 연산에 비해 너무 커서 전부 첫 버킷에 몰리므로 0.1ms부터 잡았다.
verify_duration_seconds = Histogram(
    "vps_verify_duration_seconds",
    "Time spent verifying a single proof code",
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1),
)

proofs_created_total = Counter(
    "vps_verify_proofs_created_total",
    "Total number of one-time proofs created by staff",
)

credentials_revoked_total = Counter(
    "vps_verify_credentials_revoked_total",
    "Total number of credentials revoked (e.g. resigned staff)",
)

# 클라이언트별 실패 횟수 제한(domain/rate_limit.py)에 걸려 검증하지 않고 429로 거절한 횟수.
# 늘어나면 누군가 확인 코드를 대입하고 있다는 신호다. vps_verify_requests_total에도
# reason="rate_limited"로 함께 남는다.
rate_limited_total = Counter(
    "vps_verify_rate_limited_total",
    "Total number of verification requests rejected by the per-client failure limit",
)
