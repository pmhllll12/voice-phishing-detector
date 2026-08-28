# infrastructure 계층: Prometheus 클라이언트 연동.
# 아래 5개 메트릭은 prometheus/prometheus.yml에 이미 문서화해둔 커스텀 메트릭과 이름을
# 맞춰뒀다. reports_submitted_total은 main.py의 submit_report(F-07)에서 이미 .inc()로
# 연결됨. 나머지 4개는 아직 application 계층 로직에 연결 전이라 TODO로 남겨둔다.

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

# TODO: AnalyzeCallService.execute() 안에서 위 메트릭들을 실제로 기록하도록 연결
# TODO: analysis_duration_seconds는 @analysis_duration_seconds.time() 데코레이터
#       또는 with 블록으로 감싸면 편함
