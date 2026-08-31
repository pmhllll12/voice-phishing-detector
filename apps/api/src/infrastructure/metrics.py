# infrastructure 계층: Prometheus 클라이언트 연동.
# 아래 5개 메트릭은 prometheus/prometheus.yml에 이미 문서화해둔 커스텀 메트릭과 이름을
# 맞춰뒀다. N-05(2026-08-31)로 전부 main.py에 연결 완료 — analysis_duration_seconds/
# calls_analyzed_total/risk_score_distribution은 analyze_call·analyze_call_audio에서
# _record_analysis_metrics로, deepvoice_detected_total은 check_deepvoice에서
# _record_deepvoice_metrics로, reports_submitted_total은 submit_report에서 기록한다.

from prometheus_client import Counter, Histogram

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
