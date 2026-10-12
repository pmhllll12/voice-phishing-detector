---
layout: page
title: 데이터베이스 ERD
permalink: /부록D-데이터베이스ERD/
---

이 프로젝트의 postgres 스키마는 **3개 테이블뿐**이다(`infra/db/init.sql` 전문 기준).
supersub 같은 다른 프로젝트의 32-테이블 ERD와 비교하면 극단적으로 단순한데, 의도적인
설계다 — 이 시스템이 실제로 영속시켜야 하는 건 "감사증적"과 "RAG 검색용 참고 데이터"
두 가지뿐이고, 판정 자체(위험도 스코어, 탐지 패턴, 자연어 설명)는 매 요청마다
계산되는 파생 결과라 자체 테이블 구조가 필요 없다 — `call_analysis_results`
한 테이블의 JSONB 컬럼에 그 계산 결과를 통째로 적재한다.

## D.1 한눈에 보기

```
┌─────────────────────────────┐        ┌──────────────────────┐
│  call_analysis_results       │        │   report_records      │
│  (N-01 감사증적, api)         │        │   (N-01 감사증적,       │
│  ─────────────────────────  │        │    mcp-server)         │
│  call_id            UUID PK  │        │  report_id     UUID PK │
│  raw_transcript      TEXT    │        │  case_summary  TEXT    │
│  masked_transcript   TEXT    │        │  risk_level    TEXT    │
│  risk_score          INT     │        │  channel       TEXT    │
│  risk_level          TEXT    │        │  status        TEXT    │
│  detected_patterns   JSONB   │        │  submitted_at  TSTZ    │
│  explanation_summary TEXT    │        └──────────────────────┘
│  explanation         TEXT    │           append-only 트리거
│  similar_cases       JSONB   │
│  analyzed_at         TSTZ    │        ┌──────────────────────┐
└─────────────────────────────┘        │   fraud_cases          │
   append-only 트리거                   │   (F-04, rag-worker)   │
   (두 테이블 모두 apps/api·                │  ─────────────────── │
    mcp-server가 각각 소유,               │  case_id       TEXT PK│
    서로 외래키로 얽히지 않음)              │  title         TEXT   │
                                        │  category      TEXT   │
                                        │  summary       TEXT   │
                                        │  source_note   TEXT   │
                                        │  embedding vector(768) │
                                        └──────────────────────┘
                                           append-only 트리거 없음
                                           (검색용 참고 데이터,
                                            seed 스크립트로 갱신)
```

세 테이블 사이에 외래키 관계는 없다 — `call_analysis_results.similar_cases`가
`fraud_cases`의 검색 결과를 JSONB로 **복사해 저장**한다(참조가 아니라 스냅샷).
판정 시점에 "왜 그렇게 판단했는가"의 근거를 그대로 얼려서 감사증적에 남겨야 하는데,
외래키로 참조만 해두면 `fraud_cases`가 나중에 갱신됐을 때 과거 판정의 근거가 조용히
바뀌어 보이는 문제가 생긴다 — 감사증적의 불변성(N-01)을 지키려면 참조가 아니라
복사가 맞는 선택이다.

## D.2 call_analysis_results — N-01 감사증적 (api 소유)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| call_id | UUID | PK | 판정 1건의 식별자 |
| raw_transcript | TEXT | NOT NULL | 원문 통화/문자 텍스트 — ADMIN 권한에서만 API 응답에 노출(N-02×N-03) |
| masked_transcript | TEXT | nullable | N-03 마스킹된 버전 — VIEWER 이상 누구나 열람 가능 |
| risk_score | INTEGER | NOT NULL | F-02, 0~100 |
| risk_level | TEXT | NOT NULL | 저/중/고 |
| detected_patterns | JSONB | NOT NULL | F-01 탐지된 카테고리/키워드 목록 |
| explanation_summary | TEXT | NOT NULL | F-05 요약 설명 |
| explanation | TEXT | NOT NULL | F-05 상세 설명 |
| similar_cases | JSONB | NOT NULL, 기본값 `[]` | F-04 검색된 유사사례 스냅샷 |
| analyzed_at | TIMESTAMPTZ | NOT NULL | 판정 시각. `idx_call_analysis_results_analyzed_at`로 최신순 조회(F-06) 인덱싱 |

`masked_transcript`는 `ADD COLUMN IF NOT EXISTS`로 추가됐다 — N-03(2026-08-31)이
`call_analysis_results` 테이블 자체보다 나중에 도입됐기 때문에, NOT NULL 제약을 걸면
그 이전에 쌓인 행이 마이그레이션을 실패시킨다. 그래서 nullable로 두고, 애플리케이션이
그 시점 이후로는 항상 채우도록 보장한다(`PostgresCallLogRepository.add`).

## D.3 report_records — N-01 감사증적 (mcp-server 소유)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| report_id | UUID | PK | 신고 접수 1건의 식별자 |
| case_summary | TEXT | NOT NULL | 신고 사유 요약 |
| risk_level | TEXT | NOT NULL | 신고 시점의 위험도 |
| channel | TEXT | NOT NULL | `auto`(고위험 자동 신고) \| `manual`(수동 신고) |
| status | TEXT | NOT NULL | 접수 상태 (mock — 실제 112/경찰청 API 미연동) |
| submitted_at | TIMESTAMPTZ | NOT NULL | 접수 시각. `idx_report_records_submitted_at`로 최신순 인덱싱 |

## D.4 fraud_cases — F-04 유사사례 검색 (rag-worker 소유, pgvector)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| case_id | TEXT | PK | 사기유형 사례 식별자 |
| title | TEXT | NOT NULL | 사례 제목 |
| category | TEXT | NOT NULL | 카테고리(기관사칭/공포조성/긴급송금유도/개인정보요구) |
| summary | TEXT | NOT NULL | 사례 요약 |
| source_note | TEXT | NOT NULL | 출처(뉴스/경찰청 공개자료 등) 표기 |
| embedding | vector(768) | NOT NULL | `jhgan/ko-sroberta-multitask`로 계산한 정규화 임베딩. 코사인 거리 연산자(`<=>`)로 검색 |

다른 두 테이블과 달리 append-only 트리거가 없다 — 감사증적이 아니라 검색용 참고
데이터이기 때문이다. 데이터셋을 갱신할 때는 `apps/rag-worker/scripts/seed_fraud_cases.py`
로 `fraud_cases.json`(소스 오브 트루스)을 다시 upsert한다. ANN 인덱스(ivfflat/hnsw)는
아직 만들지 않았다 — 코퍼스가 10건 규모라 순차 스캔(exact search) 비용이 무시할
수준이기 때문이며, 데이터셋이 수만 건 규모로 커지면 그때 추가한다(`init.sql` 주석).

## D.5 append-only 강제 — 트리거 구현

N-01("모든 판정 과정을 변경 불가능한 로그로 기록")을 애플리케이션 코드의 규율이
아니라 DB 레벨에서 강제한다.

```sql
CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'N-01: append-only 감사증적 테이블(%)은 UPDATE/DELETE를 허용하지 않습니다', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;
```

이 함수를 `call_analysis_results`, `report_records` 양쪽에 `BEFORE UPDATE OR DELETE`
트리거로 건다. "애플리케이션 코드가 UPDATE 문을 만들지 않는다"는 것만으로는 향후 코드
변경 실수로 규칙이 깨질 여지가 남지만, DB 트리거는 어떤 클라이언트(애플리케이션 코드든,
누군가 직접 붙인 `psql`이든)로 접근하든 예외 없이 거부한다 — 코드 리뷰보다 강한
수준의 보장이다.

## D.5b channel_signals — 크로스채널 상관관계 탐지 (mcp-server 소유, 2026-09-02 추가)

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| signal_id | UUID | PK(복합) | 한 채널 이벤트(통화/문자/이메일 1건)에서 추출된 엔티티들을 묶는 식별자 — 엔티티가 여러 개면 같은 signal_id로 여러 행이 생긴다 |
| channel | TEXT | PK(복합) | call / sms / email |
| entity_type | TEXT | PK(복합) | phone / account / url |
| entity_value | TEXT | PK(복합) | 정규화된 원본 값(숫자만/host만) — 매칭 정확도를 위해 마스킹하지 않고 저장한다. API/툴 응답으로 나갈 때는 항상 마스킹한다(N-03과 같은 원칙) |
| occurred_at | TIMESTAMPTZ | NOT NULL | 이벤트 발생 시각. 인덱스(`entity_type, entity_value, occurred_at DESC`)로 "같은 값이 다른 채널에 시간 윈도우 안에 등장했는가" 조회를 지원 |
| context_excerpt | TEXT | NOT NULL | 근거 문장 생성용 발췌 |

다른 4개 테이블과 달리 append-only 트리거가 없다 — `fraud_cases`와 같은 이유로
"판정 원본 기록"이 아니라 "상관관계 조회용 파생 인덱스"이기 때문이다.

**이 테이블이 왜 새로 생겼는가**: 우선순위 2(크로스채널 상관관계 탐지) 작업지시서는
"AUDIT_LOGS가 이미 `entity_type`+`entity_id`로 범용 참조하게 설계되어 있어 새 테이블이
불필요하다"고 가정했다. 실제로 이 문서(D장) 재검증 결과 그런 범용 참조 컬럼은 어느
테이블에도 없었다 — 그래서 목적 전용 테이블을 새로 추가했다. N-06(확장성) 관점에서는
오히려 유의미한 결과다: "포트-어댑터 확장"(알고리즘 교체, D.4 참고)과 "완전히 새로운
질의 축 추가"(스키마 확장이 필요한 경우)를 구분해서 보여주는 사례이기 때문 —
전자는 애플리케이션 계층만 바꾸면 되지만, 후자는 정직하게 스키마 변경이 필요하다는
걸 이 사례가 실증한다.

## D.6 왜 이렇게 단순한가

`fraud_cases`/`channel_signals`를 제외하면 이 시스템에 "관계"라고 부를 만한 구조가
거의 없다. 이는 설계 누락이 아니라, **판정 도메인 모델(`CallAnalysisResult`,
`DeepvoiceVerdict` 등)이 전부 무상태(stateless) 계산 결과**라는 이 시스템의 성격을
그대로 반영한 것이다 — 사용자 계정, 팀, 매칭, 과금처럼 여러 엔터티가 서로 참조하며
상태를 갖는 도메인(예: supersub의 32-테이블 스키마)과 달리, 이 시스템은 "입력(통화/
문자) → 계산(판정) → 기록(감사증적)"의 단방향 파이프라인이라 테이블 간 조인이 필요한
질의 자체가 거의 발생하지 않는다. F-04(유사사례 검색)는 벡터 검색이, 크로스채널
상관관계 탐지(D.5b)는 엔티티 값 조회가 필요해 각각 별도 테이블을 가진다.

[← 목차로]({{ "/toc/" | relative_url }})
