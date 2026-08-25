# infrastructure 계층: Prometheus 클라이언트 연동.
# apps/rag-worker/src/infrastructure/metrics.py와 동일한 패턴(vps_ 접두사)을 따른다.
#
# WHY GPU 메모리를 torch로 안 재는가: apps/rag-worker는 mcp-server 프로세스 안에서
# 직접 torch로 GPU를 잡지만, LLM 추론은 Ollama가 별도 프로세스(별도 CUDA 컨텍스트)로
# 돌기 때문에 mcp-server 쪽에서는 torch.cuda 같은 걸로 잴 대상 자체가 없다.
# 대신 Ollama가 자기 자신의 GPU 사용량을 알려주는 GET /api/ps 응답의
# models[].size_vram 값을 그대로 가져다 쓴다 (ollama_call_analysis_adapter.py 참고).
# 이 프로젝트에서 GPU 한 장을 "임베딩 모델을 올린 rag-worker 프로세스"와
# "LLM을 올린 Ollama 프로세스"가 동시에 나눠 쓰는데, 그 둘을 각자 자기 프로세스
# 기준으로 관측하는 방식이 다르다는 게 이 부분의 포인트다.

from prometheus_client import Counter, Gauge, Histogram, Info

# F-01/F-02: LLM 호출 1건에 걸린 시간 (Ollama 응답의 total_duration 기준)
llm_inference_duration_seconds = Histogram(
    "vps_mcp_llm_inference_duration_seconds",
    "Time spent on a single Ollama analyze call (including cold-start model load)",
)

# F-01/F-02: 통화 분석 요청 수. result="fallback"은 Ollama 호출이 실패(타임아웃/
# 모델 미로드/JSON 파싱 실패 등 사유 불문)해서 규칙 기반(v1)으로 안전하게 넘어간
# 경우 — 이 값이 계속 올라가면 LLM 쪽에 문제가 있다는 신호로 알림에 쓸 수 있다.
llm_analysis_requests_total = Counter(
    "vps_mcp_llm_analysis_requests_total",
    "Total number of call-analysis requests handled via the LLM path",
    labelnames=["result"],  # "success" | "fallback"
)

# Ollama가 보고하는, 현재 이 모델이 점유 중인 GPU 메모리 (bytes). 모델이 언로드되면 0.
llm_gpu_memory_bytes = Gauge(
    "vps_mcp_llm_gpu_memory_bytes",
    "GPU memory currently held by the loaded Ollama model, per GET /api/ps (bytes)",
)

# 모델이 콜드 스타트로 로딩된 경우 그 로딩 시간 (Ollama 응답의 load_duration, 초 단위).
# 이미 로드돼서 캐시 히트면 거의 0에 가깝다.
llm_model_load_duration_seconds = Gauge(
    "vps_mcp_llm_model_load_duration_seconds",
    "Model load duration reported by Ollama for the most recent call (seconds)",
)

llm_model_info = Info(
    "vps_mcp_llm_model",
    "Ollama model name and processor placement (e.g. 100% GPU) currently in use",
)
