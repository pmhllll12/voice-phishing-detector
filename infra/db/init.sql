-- N-01 감사증적 스키마 — api(call_analysis_results)와 mcp-server(report_records)의
-- 인메모리 저장소(InMemoryCallLogRepository/InMemoryReportRepository)를 대체한다.
--
-- append-only 강제: N-01은 "변경 불가능한(append-only) 로그"를 요구한다. 애플리케이션
-- 코드가 UPDATE/DELETE를 아예 안 만든다는 것만으로는 "코드 실수로 언젠가 추가될 수
-- 있다"는 리스크가 남으므로, DB 트리거로 UPDATE/DELETE 자체를 거부한다 — 코드가 어떻게
-- 바뀌든 이 두 테이블에서 기존 행을 고치거나 지우는 것은 물리적으로 불가능하다.
--
-- rag-worker의 fraud_cases(F-04)는 이 마이그레이션 범위 밖이다 — 감사증적이 아니라
-- 검색용 참고 데이터라 append-only 요구사항이 적용되지 않고, 지금 규모(10건)에서는
-- 로컬 JSON으로 충분하다 (apps/rag-worker/src/infrastructure/data_loader.py 참고).

CREATE TABLE IF NOT EXISTS call_analysis_results (
    call_id UUID PRIMARY KEY,
    raw_transcript TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    detected_patterns JSONB NOT NULL,
    explanation_summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    similar_cases JSONB NOT NULL DEFAULT '[]'::jsonb,
    analyzed_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_call_analysis_results_analyzed_at
    ON call_analysis_results (analyzed_at DESC);

CREATE TABLE IF NOT EXISTS report_records (
    report_id UUID PRIMARY KEY,
    case_summary TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_report_records_submitted_at
    ON report_records (submitted_at DESC);

CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'N-01: append-only 감사증적 테이블(%)은 UPDATE/DELETE를 허용하지 않습니다', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS call_analysis_results_append_only ON call_analysis_results;
CREATE TRIGGER call_analysis_results_append_only
    BEFORE UPDATE OR DELETE ON call_analysis_results
    FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

DROP TRIGGER IF EXISTS report_records_append_only ON report_records;
CREATE TRIGGER report_records_append_only
    BEFORE UPDATE OR DELETE ON report_records
    FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
