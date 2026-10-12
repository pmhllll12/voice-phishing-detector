# infrastructure 계층: Prometheus 클라이언트 연동.
# 아래 메트릭은 prometheus/prometheus.yml에 이미 문서화해둔 커스텀 메트릭과 이름을
# 맞춰뒀다. N-05(2026-08-31)로 전부 main.py에 연결 완료 — analysis_duration_seconds/
# calls_analyzed_total/risk_score_distribution은 analyze_call·analyze_call_audio에서
# _record_analysis_metrics로, deepvoice_detected_total은 check_deepvoice에서
# _record_deepvoice_metrics로, reports_submitted_total은 submit_report에서 기록한다.
#
# deepvoice_inference_duration_seconds/deepvoice_model_load_duration_seconds/
# deepvoice_model_info는 F-03 v2(wav2vec2_deepvoice_adapter.py) 전용 서빙 메트릭이다
# — rag-worker(vps_rag_*)/stt-worker(vps_stt_*)가 이미 갖고 있는
# "*_inference_duration_seconds / *_model_load_duration_seconds / *_model_info" 3종
# 패턴을 F-03에도 그대로 맞췄다. GPU 메모리 게이지는 의도적으로 만들지 않았다 —
# wav2vec2_deepvoice_adapter.py가 항상 CPU로 고정 실행되므로(그 파일 "WHY CPU" 주석
# 참고) 값이 항상 0인 지표를 추가하는 건 신호가 아니라 노이즈다.

from prometheus_client import Counter, Gauge, Histogram, Info

# F-01/F-02: 처리된 통화/문자 건수 (위험도 등급별)
calls_analyzed_total = Counter(
    "vps_calls_analyzed_total",
    "Total number of calls/messages analyzed",
    labelnames=["risk_level"],
)

# F-02: 위험도 스코어 분포
risk_score_distribution = Histogram(
    "vps_risk_score_distribution",
    "Distribution of computed risk scores (0-100)",
    buckets=[10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
)

# F-03: 딥보이스 판별 결과
deepvoice_detected_total = Counter(
    "vps_deepvoice_detected_total",
    "Total number of deepvoice detection results",
    labelnames=["result"],  # "synthetic" | "authentic"
)

# N-05: 분석 소요 시간 (5초 이내 SLA 검증용)
analysis_duration_seconds = Histogram(
    "vps_analysis_duration_seconds",
    "Time spent analyzing a single call/message",
)

# F-07: 신고 접수 건수
reports_submitted_total = Counter(
    "vps_reports_submitted_total",
    "Total number of reports submitted",
    labelnames=["channel"],  # "auto" | "manual"
)

# F-03 v2: 모델 추론 1건(오디오 1건 판별)에 걸린 시간 — 콜드스타트 로딩 시간은
# 포함하지 않는다(그건 아래 model_load_duration_seconds가 별도로 잰다).
deepvoice_inference_duration_seconds = Histogram(
    "vps_deepvoice_inference_duration_seconds",
    "Time spent running the wav2vec2 spoofing-detection model on a single audio clip",
)

# F-03 v2: 서버 시작 시 모델 로딩(1회)에 걸린 시간. 모델 로드/라벨 매핑 실패로
# v1로 폴백한 경우에는 기록되지 않는다(로딩 자체가 끝까지 성공하지 못했으므로).
deepvoice_model_load_duration_seconds = Gauge(
    "vps_deepvoice_model_load_duration_seconds",
    "Time spent loading the F-03 v2 deepvoice model at server startup",
)

# 어떤 모델/디바이스로 떠 있는지 — device는 항상 "cpu"로 고정이다(어댑터 상단 주석
# "WHY CPU" 참고). 모델 로드 실패로 v1 폴백 중이면 이 Info는 세팅되지 않는다.
deepvoice_model_info = Info(
    "vps_deepvoice_model",
    "F-03 v2 deepvoice model name and inference device currently in use",
)
