# infrastructure 계층: Prometheus 클라이언트 연동.
# apps/rag-worker, apps/mcp-server의 src/infrastructure/metrics.py와 동일한 패턴(vps_ 접두사)을
# 따른다.
#
# WHY GPU 메모리를 rag-worker처럼 torch.cuda.memory_allocated()로 못 재는가: faster-whisper는
# torch가 아니라 ctranslate2(자체 CUDA 커널)로 동작해서, "이 프로세스가 지금 몇 바이트 쓰는지"를
# 알려주는 파이썬 API가 없다. 그렇다고 mcp-server처럼 엔진이 자기 자신의 VRAM을 알려주는
# API(Ollama의 GET /api/ps)가 있는 것도 아니다.
#
# 그래서 이 서비스만 다른 방식을 쓴다: 모델 로딩 "전/후"에 nvidia-ml-py(NVML)로 GPU 전체
# 사용량을 찍어 그 차이를 이 프로세스의 VRAM 사용량으로 근사한다. 정확한 프로세스별 값이
# 아니라 "로딩 전후 델타"라는 한계가 있어 메트릭 이름에도 굳이 delta를 붙였다 — 같은 시점에
# 다른 프로세스가 GPU 메모리를 늘리거나 줄이면 이 값이 왜곡될 수 있다(예: Ollama가 동시에
# 모델을 로드/언로드하는 순간과 겹치면 오차 발생). WSL2에서는 NVML의 프로세스별 사용량 조회
# (nvmlDeviceGetComputeRunningProcesses().usedGpuMemory)가 None을 반환해서(드라이버 제약,
# 직접 확인함) 이 방식을 쓸 수밖에 없었다 — 네이티브 리눅스 등 NVML이 프로세스별 값을 정상
# 지원하는 환경으로 옮기면 그쪽 API로 교체할 것.

import logging

import pynvml
from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)

# F-01/F-02 모바일 파이프라인: 오디오 청크 1건을 텍스트로 변환하는 데 걸린 시간
inference_duration_seconds = Histogram(
    "vps_stt_inference_duration_seconds",
    "Time spent transcribing a single audio chunk",
)

# 변환 요청 수 (성공/실패)
transcription_requests_total = Counter(
    "vps_stt_transcription_requests_total",
    "Total number of audio transcription requests",
    labelnames=["result"],  # "success" | "error"
)

# 서버 시작 시 모델 로딩(1회)에 걸린 시간
model_load_duration_seconds = Gauge(
    "vps_stt_model_load_duration_seconds",
    "Time spent loading the STT model at server startup",
)

# 모델 로딩 전/후 GPU 전체 사용량 델타 (위 WHY 설명 참고) — CPU로 폴백 중이면 0.
gpu_memory_delta_bytes = Gauge(
    "vps_stt_gpu_memory_delta_bytes",
    "Approximate GPU memory added by this process, measured as the total-GPU-usage "
    "delta across model load (0 when running on CPU)",
)

# 어떤 모델/디바이스/양자화로 떠 있는지
stt_model_info = Info(
    "vps_stt_model",
    "STT model name, device, and compute type currently in use",
)


def read_total_gpu_memory_used() -> int | None:
    """NVML로 GPU 0의 전체(모든 프로세스 합산) 사용량을 바이트 단위로 읽는다.
    GPU가 없거나 NVML 초기화에 실패하면 None을 반환한다."""
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.used)
    except pynvml.NVMLError as e:
        logger.warning("NVML로 GPU 메모리 조회 실패 — GPU 메트릭을 0으로 둔다: %s", e)
        return None
