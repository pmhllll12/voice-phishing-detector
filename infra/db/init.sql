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

-- SMS/email 실채널 연동(2026-09-02): F-01/F-02/F-05 판정 로직은 채널 무관하게 같은
-- CallAnalysisService.execute(channel=...)를 재사용하므로, 감사증적도 어느 채널에서
-- 왔는지만 컬럼 하나로 구분한다(call/email/sms — 새 테이블을 만들 정도로 구조가
-- 다르지 않음). NOT NULL + DEFAULT라 기존 행(전부 call이었음)도 즉시 채워진다
-- (masked_transcript처럼 nullable로 둘 필요가 없음 — 이 값은 항상 알 수 있음).
ALTER TABLE call_analysis_results ADD COLUMN IF NOT EXISTS channel TEXT NOT NULL DEFAULT 'call';

-- F-06 대시보드 UI/UX 개선(2026-09-02, item 1/2/3): 크로스채널 상관관계 가산 "전" 원점수와
-- 그 가산 근거를 감사증적에도 영구 보존한다 — 지금까지는 응답 dict에만 실려서 최초 판정
-- 직후 화면에서만 보였고, 새로고침/재조회하면 사라졌다(risk_score/explanation에는 이미
-- 병합된 값만 남아 있어서 "원래 몇 점이었는지"를 되돌릴 수 없었음). 둘 다 nullable인 이유는
-- masked_transcript와 같다 — 이 컬럼 도입 이전 행에는 값이 없다(NULL이면 상관관계 가산이
-- 없었던 것으로 표시).
ALTER TABLE call_analysis_results ADD COLUMN IF NOT EXISTS base_risk_score INTEGER;
ALTER TABLE call_analysis_results ADD COLUMN IF NOT EXISTS correlation_matches JSONB NOT NULL DEFAULT '[]'::jsonb;

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

-- N-06 확장성 검증 겸 크로스채널 상관관계 탐지(우선순위 2, 2026-09-02): 통화/문자/이메일
-- 등 서로 다른 채널의 탐지 기록에서 동일 전화번호/계좌번호/URL이 시간 윈도우 안에
-- 반복 등장하면 위험도를 가산한다(apps/mcp-server/src/application/services.py의
-- MultichannelCorrelationService 참고).
--
-- 원래 작업지시서는 "docs/erd.md의 AUDIT_LOGS가 이미 entity_type+entity_id로 범용
-- 참조하게 설계되어 있어 새 테이블이 불필요하다"고 가정했지만, 실제로는 그런 파일/컬럼이
-- 존재하지 않았다(레포 재검증으로 확인) — 그래서 이 목적 전용 테이블을 새로 추가한다.
-- call_analysis_results/report_records(N-01 감사증적)와 달리 이 테이블은 "판정 원본
-- 기록"이 아니라 "상관관계 조회용 파생 인덱스"라 append-only 트리거를 적용하지 않는다
-- (fraud_cases와 같은 성격 — 위 주석 참고).
CREATE TABLE IF NOT EXISTS channel_signals (
    signal_id UUID NOT NULL,
    channel TEXT NOT NULL,       -- call | sms | email
    entity_type TEXT NOT NULL,   -- phone | account | url
    entity_value TEXT NOT NULL,  -- 정규화된 원본 값(숫자만/도메인 등) — 매칭 정확도를 위해 마스킹하지 않고 저장한다.
                                  -- 조회 결과를 바깥으로 내보낼 때는 항상 마스킹한다(masked_signal.py의
                                  -- _mask_for_display 참고) — N-03과 같은 "저장은 원문, 노출은 마스킹" 원칙.
    occurred_at TIMESTAMPTZ NOT NULL,
    context_excerpt TEXT NOT NULL,
    PRIMARY KEY (signal_id, entity_type, entity_value)
);

CREATE INDEX IF NOT EXISTS idx_channel_signals_entity_lookup
    ON channel_signals (entity_type, entity_value, occurred_at DESC);

-- F-06 대시보드 "근거 연결"(2026-09-02): 이 신호를 발생시킨 원본 판정 기록의 식별자
-- (apps/api call_analysis_results.call_id) — apps/api 경유 호출만 채운다. nullable인
-- 이유는 apps/api를 거치지 않는 경로(MCP stdio 자동 결합, correlate_multichannel_signals
-- 툴의 합성 데이터 주입)는 call_id 개념이 없어서다 — 그런 신호는 근거 문장만 보여주고
-- 클릭 이동은 못 한다(domain/entities.py의 ChannelSignal.source_ref 상단 주석 참고).
ALTER TABLE channel_signals ADD COLUMN IF NOT EXISTS source_ref TEXT;
