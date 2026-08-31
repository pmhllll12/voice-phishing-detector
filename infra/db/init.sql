-- N-01 감사증적 스키마 — api(call_analysis_results)와 mcp-server(report_records)의
-- 인메모리 저장소(InMemoryCallLogRepository/InMemoryReportRepository)를 대체한다.
--
-- append-only 강제: N-01은 "변경 불가능한(append-only) 로그"를 요구한다. 애플리케이션
-- 코드가 UPDATE/DELETE를 아예 안 만든다는 것만으로는 "코드 실수로 언젠가 추가될 수
-- 있다"는 리스크가 남으므로, DB 트리거로 UPDATE/DELETE 자체를 거부한다 — 코드가 어떻게
-- 바뀌든 이 두 테이블에서 기존 행을 고치거나 지우는 것은 물리적으로 불가능하다.
--
-- rag-worker의 fraud_cases(F-04, 아래)는 call_analysis_results/report_records와 성격이
-- 다르다 — 감사증적이 아니라 검색용 참고 데이터라 append-only 트리거를 적용하지 않는다.
-- 데이터셋을 갱신할 때는 apps/rag-worker/scripts/seed_fraud_cases.py로 다시 upsert한다
-- (fraud_cases.json이 여전히 소스 오브 트루스 — pgvector 테이블은 그 파생 캐시).

CREATE TABLE IF NOT EXISTS call_analysis_results (
    call_id UUID PRIMARY KEY,
    raw_transcript TEXT NOT NULL,
    masked_transcript TEXT,
    risk_score INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    detected_patterns JSONB NOT NULL,
    explanation_summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    similar_cases JSONB NOT NULL DEFAULT '[]'::jsonb,
    analyzed_at TIMESTAMPTZ NOT NULL
);

-- N-03(2026-08-31): 기존에 이미 만들어진 테이블(위 CREATE TABLE IF NOT EXISTS는 신규
-- 테이블에만 적용됨)에도 마스킹 컬럼을 추가한다 — NOT NULL로 안 하는 이유는 이 컬럼
-- 도입 전에 쌓인 기존 행에는 값이 없어서(NULL), NOT NULL 제약을 걸면 이 마이그레이션
-- 자체가 실패한다. 도입 이후 적재되는 행은 애플리케이션이 항상 채운다
-- (PostgresCallLogRepository.add 참고).
ALTER TABLE call_analysis_results ADD COLUMN IF NOT EXISTS masked_transcript TEXT;

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

-- F-04 유사사례 검색(rag-worker) pgvector 테이블. 임베딩은 jhgan/ko-sroberta-multitask
-- (768차원, normalize_embeddings=True로 정규화)로 계산한 뒤 여기 저장한다 — 검색 시
-- pgvector의 코사인 거리 연산자(<=>)로 postgres가 직접 정렬/상위 K를 계산한다
-- (apps/rag-worker/src/infrastructure/adapters/pgvector_similarity_adapter.py 참고).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS fraud_cases (
    case_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    source_note TEXT NOT NULL,
    embedding vector(768) NOT NULL
);

-- ANN 인덱스(ivfflat/hnsw)는 아직 만들지 않는다 — 코퍼스가 10건이라 순차 스캔(exact
-- search) 비용이 무시할 만하다. 데이터셋이 수만 건 규모로 커지면 이때 추가한다.
