# infrastructure 계층: Prometheus 클라이언트 연동.
# apps/api/src/infrastructure/metrics.py와 동일한 패턴(vps_ 접두사)을 따른다.
# prometheus/prometheus.yml의 vps-rag-worker job에 이미 이름을 맞춰 문서화해뒀다.

from prometheus_client import Counter, Gauge, Histogram, Info

# F-04: 쿼리 1건을 임베딩 벡터로 변환하는 데 걸린 시간 (배치 인코딩이 아니라
# search() 1회 호출 기준 — GPU/CPU 추론 성능을 관측하려는 목적)
embedding_inference_duration_seconds = Histogram(
    "vps_rag_embedding_inference_duration_seconds",
    "Time spent encoding a single query into an embedding vector",
)

# F-04: 유사사례 검색 요청 수 (성공/실패)
embedding_search_requests_total = Counter(
    "vps_rag_embedding_search_requests_total",
    "Total number of similar-case search requests",
    labelnames=["result"],  # "success" | "error"
)

# 서버 시작 시 모델 로딩(1회)에 걸린 시간 — 값이 바뀌지 않는 단발성 지표라 Gauge로 충분
model_load_duration_seconds = Gauge(
    "vps_rag_model_load_duration_seconds",
    "Time spent loading the embedding model at server startup",
)

# 이 프로세스가 현재 점유 중인 GPU 메모리 (torch.cuda.memory_allocated 기준).
# GPU가 없거나 CPU 폴백 중이면 0으로 유지된다.
gpu_memory_allocated_bytes = Gauge(
    "vps_rag_gpu_memory_allocated_bytes",
    "GPU memory currently allocated by this process (bytes), 0 when running on CPU",
)

# 어떤 모델/디바이스로 떠 있는지 (Grafana에서 배포 구성을 라벨로 바로 확인하기 위함)
embedding_model_info = Info(
    "vps_rag_embedding_model",
    "Embedding model name and inference device currently in use",
)
