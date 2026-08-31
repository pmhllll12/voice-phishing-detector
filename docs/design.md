# 설계서 (System Design)

> **진행 상황**(2026-08-31 갱신): 시스템 아키텍처/데이터 모델/API 명세/N-06 확장성
> 챕터를 채웠다. **배포 구조(EC2/보안그룹/도메인) 챕터만 아직 TODO** — 실제 배포를
> 아직 하지 않아서(`docker-compose.yaml` 로컬 실기동까지만 완료, README "진행 현황"
> 참고) 쓸 내용이 없다. 배포가 완료되면 이 문서에 추가한다.

## 1. 시스템 아키텍처

### 1.1 구성도

```
frontend (Next.js, 관제 대시보드)
   │
   ▼
api (FastAPI) ──► mcp-server (통화분석/사기패턴DB조회/신고연동 툴) ──► postgres+pgvector
   │                  │                                                   ▲
   │                  └─ Ollama 로컬 LLM (EXAONE 3.5 2.4B, JSON Schema     │
   │                     강제 출력 + 규칙 기반 자동 폴백)                    │
   └──────────────► rag-worker (유사사례 임베딩/검색) ───────────────────────┘
                        │
                        └─ sentence-transformers 로컬 임베딩 모델
                           (jhgan/ko-sroberta-multitask) + 코사인 유사도

stt-worker (faster-whisper, 모바일 오디오→텍스트) ◄── api (F-05 오디오 경로)

prometheus ──► grafana  (애플리케이션 메트릭 관측)
```

5개 서비스 + postgres + prometheus/grafana로 구성된다. 각 서비스의 담당 요구사항은
`docs/requirements.md` 4장 요구사항 추적표 참고.

### 1.2 헥사고날 아키텍처

`apps/api`, `apps/mcp-server`, `apps/rag-worker` 세 Python 앱 모두 동일한 계층
구조를 따른다(`CLAUDE.md`).

```
domain/          "무엇을 판단하는가" — 프레임워크/DB/외부 API를 전혀 모르는 순수 모델 + 포트
application/     "어떤 순서로 조합하는가" — 유스케이스. domain의 포트에만 의존
infrastructure/  "실제로 어떻게 하는가" — 포트 구현체(어댑터), FastAPI 진입점, DB 연결
```

의존 방향은 `infrastructure → application → domain` 한 방향으로만 흐른다. 이
원칙이 실제로 지켜지고 있다는 근거는 4장(N-06 확장성 설계)의 포트-어댑터 4회
교체 실증이다 — 이론이 아니라 실측이다.

### 1.3 판정 파이프라인

텍스트 경로(F-01/F-02)와 오디오 경로(F-05)는 입력 앞단만 다르고, 그 뒤 판정
파이프라인은 동일하다.

```
[통화/문자 텍스트]                    [모바일 오디오 청크]
        │                                     │
        │                              stt-worker (faster-whisper)
        │                                     │
        ▼                                     ▼
             apps/api: N-03 PII 마스킹 (전화번호/계좌번호/이름)
                             │
                             ▼
            mcp-server: analyze_call_pattern (F-01/F-02)
                             │
                             ▼
            mcp-server: lookup_fraud_pattern_db (F-04, rag-worker 호출)
                             │
                             ▼
              F-05: 탐지 패턴 + 자연어 설명 + 유사사례 결합
                             │
                             ▼
              apps/api: N-01 감사증적 적재 + N-05 메트릭 기록
                             │
                             ▼
                  (고위험이면) F-07 신고 접수 mock 호출
```

## 2. 데이터 모델

전체 스키마는 3개 테이블뿐이다(`infra/db/init.sql`) — `call_analysis_results`
(N-01, api 소유), `report_records`(N-01, mcp-server 소유), `fraud_cases`(F-04,
pgvector, rag-worker 소유). 상세 컬럼/제약조건/append-only 트리거 구현과, 왜
이렇게 단순한지에 대한 설계 근거는 [`jekyll/chapters/부록D-데이터베이스ERD.markdown`](../jekyll/chapters/부록D-데이터베이스ERD.markdown)
에 정리해뒀다(이 문서에 중복 기술하지 않는다 — 소스 오브 트루스를 하나로 유지).

핵심만 요약하면:
- 세 테이블 사이에 외래키 관계가 없다 — `similar_cases`는 `fraud_cases` 검색
  결과를 JSONB로 **복사**해서 저장한다(참조가 아님). 감사증적의 불변성(N-01)을
  지키려면 나중에 `fraud_cases`가 바뀌어도 과거 판정 근거가 조용히 바뀌면
  안 되기 때문이다.
- `call_analysis_results`/`report_records`만 append-only 트리거가 걸려있다.
  `fraud_cases`는 검색용 참고 데이터라 감사증적이 아니므로 걸지 않는다.

## 3. API 명세

각 서비스의 REST 엔드포인트 전체 목록(Method/Path/최소 권한/설명)은
[`jekyll/chapters/부록B-관련서식.markdown`](../jekyll/chapters/부록B-관련서식.markdown)
에 정리해뒀다. mcp-server는 REST 어댑터(`rest_server.py`, api가 호출) 외에
MCP stdio 진입점(`server.py`, Claude Code가 `.mcp.json`으로 직접 호출)도 갖는데,
두 진입점이 같은 application 서비스를 재사용하지만 배선 코드는 아직 복붙 상태다
(4장 "확장성이 아직 검증 안 된 지점" 참고).

## 4. 배포 구조 (TODO)

EC2 + Cloudflare Tunnel 배포가 아직 진행 전이라 이 챕터는 비워둔다. 배포
완료 시 아래를 채운다: EC2 인스턴스 스펙, 보안그룹 규칙, 도메인/DNS 구성,
Nginx 리버스 프록시 설정, Cloudflare Tunnel 연결 방식(gpu-fleet-ops에서
재사용할 패턴, README "재사용한 인프라 스킬" 참고).

## 5. N-06 확장성 설계

### 요구사항

> N-06 | 확장성 | 신규 사기유형 추가 시 시스템 재설계 없이 확장 가능한 구조로 설계한다
> (`docs/RFP.md` 3장)

### 핵심 원칙: 포트-어댑터로 "무엇을 하는가"와 "어떻게 하는가"를 분리한다

이 프로젝트의 모든 앱(`apps/api`, `apps/mcp-server`, `apps/rag-worker`)은 헥사고날
아키텍처를 따른다(`CLAUDE.md` 참고):

```
domain/          "무엇을 판단하는가" — 순수 모델 + 포트(인터페이스). 프레임워크/DB/외부
                 API를 전혀 모른다.
application/     "어떤 순서로 조합하는가" — 유스케이스. domain의 포트에만 의존한다.
infrastructure/  "실제로 어떻게 하는가" — 포트를 구현하는 어댑터, FastAPI 진입점, DB 연결.
```

확장성의 근거는 단순하다 — **domain과 application은 infrastructure를 모르므로,
infrastructure를 통째로 갈아끼워도(알고리즘 교체, 저장소 교체, 새 카테고리 추가) 위쪽
계층은 파급을 받지 않는다.** 아래는 이게 이론이 아니라 이 프로젝트에서 **이미 4번
실제로 일어난 일**이라는 근거다.

### 확장 지점별 현황

| # | 무엇을 바꾸는 지점인가 | Port(인터페이스) | 현재 구현체 | 실제 교체 이력 | application 계층 diff |
|---|---|---|---|---|---|
| 1 | F-01/F-02 판정 알고리즘 | `CallAnalysisPort` | `RuleBasedCallAnalysisAdapter`(v1, 폴백용으로 유지) / `OllamaCallAnalysisAdapter`(v2, 기본값) | v1→v2 (커밋 `360ffde`) | 0줄 |
| 2 | F-04 유사사례 검색 알고리즘 | `FraudCaseSearchPort` | `TfidfSimilarityAdapter`(v1, 디버그 비교용) / `EmbeddingSimilarityAdapter`(v2) / `PgvectorSimilarityAdapter`(v3, 기본값) | v1→v2 (`2d60b87`), v2→v3 (`960e96e`) | 0줄 |
| 3 | N-01 감사증적 저장소 | `CallLogPort` / `ReportRepositoryPort` | `InMemory*`(테스트 전용) / `Postgres*`(운영) | InMemory→Postgres (`bd68902`) | 0줄 |
| 4 | F-03 딥보이스 판별기 | `DeepvoiceDetectionPort` | `HeuristicDeepvoiceAdapter`(v1, 폴백 겸 N-04 보조 지표용으로 유지) / `Wav2Vec2DeepvoiceAdapter`(v2, 기본값) | v1→v2 (2026-08-31, `wav2vec2_deepvoice_adapter.py`) | 0줄 |
| 5 | F-01 사기유형 카테고리 | `PatternCategory` enum + `PATTERN_RULES` dict | 4종(기관사칭/공포조성/긴급송금유도/개인정보요구) | 스캐폴딩 초기 커밋부터 4번째 카테고리를 "확장 예시"로 포함 | 0줄 |
| 6 | N-02 접근권한 역할 | `Role` enum + `role_satisfies` 계층 | VIEWER/HANDLER/ADMIN 3단계, apps/api·mcp-server 양쪽에 동일 구조 | apps/api 도입 → mcp-server로 확장(`c9799af`, 같은 패턴 복붙) | 0줄 |

"application 계층 diff 0줄"은 각 커밋 메시지에 실제로 명시돼 있다. 예를 들어 F-04
v1→v2 커밋(`2d60b87`)은 "FraudCaseSearchPort 인터페이스를 그대로 유지해
application/services.py와 기존 TF-IDF 어댑터·테스트는 손대지 않았다"라고 적혀 있고,
F-01/F-02 v1→v2 커밋(`360ffde`)도 "F-04 임베딩 교체 때와 같은 포트-어댑터 패턴을
새로 도입해 인터페이스를 보존했다"라고 적혀 있다 — 두 번째 교체부터는 첫 번째 교체
경험을 명시적으로 재사용한 것이다.

### 확장 절차: 새 사기유형(카테고리) 추가하기

가장 자주 일어날 확장(N-06이 원래 염두에 둔 시나리오)은 새로운 보이스피싱 수법이
나타났을 때 카테고리를 추가하는 것이다. 실제 절차:

1. `apps/mcp-server/src/domain/entities.py`의 `PatternCategory`에 항목 추가,
   `CATEGORY_LABELS`에 한글 라벨 추가.
2. `apps/mcp-server/src/domain/pattern_rules.py`의 `PATTERN_RULES`에 키워드셋 추가
   (규칙 기반 v1용), `CATEGORY_WEIGHTS`에 F-02 가중치 추가.
3. (선택, 시각적 구분이 필요할 때만) `apps/frontend/src/lib/categories.ts`의
   `CATEGORY_COLOR_ORDER`에 등록 — 등록을 안 해도 대시보드가 깨지지는 않는다.
   `colorForCategory()`가 미등록 카테고리를 회색(`var(--text-muted)`)으로 그레이스풀
   폴백하기 때문이다(`categories.ts` 참고). 다만 다른 카테고리와 시각적으로 구분하려면
   등록해야 한다.

이걸로 끝이다. **LLM 백엔드(v2, 기본값)는 손댈 필요가 없다** —
`ollama_call_analysis_adapter.py`가 판정 프롬프트에 넣는 카테고리 목록/JSON Schema의
enum을 `PatternCategory`에서 매 요청 동적으로 생성하기 때문에(`_CATEGORY_VALUES`,
`_CATEGORY_GUIDE`), 1)에서 enum에 항목을 추가하는 순간 LLM 프롬프트에도 자동으로
반영된다. `application/services.py`(판정 오케스트레이션), `apps/api`의 라우팅/직렬화,
F-06 대시보드 집계(`compute_stats_summary`)도 전부 카테고리를 하드코딩하지 않고
`DetectedPattern`이 들고 있는 값을 그대로 순회하므로 자동으로 새 카테고리를 반영한다.

이 절차는 추정이 아니다 — `personal_info_request`(개인정보요구)가 정확히 이 방식으로
추가된 4번째 카테고리이고(초기 커밋부터 "확장 예시로 추가"라는 주석과 함께 존재),
F-01/F-02 합성 데이터셋 검증(`767eac1`)에서 나머지 3개 카테고리와 동일하게 정밀도/
재현율이 검증됐다.

### 왜 이게 "재설계 없는 확장"이라고 말할 수 있는가

- domain은 infrastructure를 import하지 않으므로, 판정 알고리즘(규칙→LLM)이나 검색
  알고리즘(TF-IDF→임베딩→pgvector)을 통째로 바꿔도 domain 모델(`CallAnalysisResult`,
  `PatternCategory` 등)은 그대로다.
- application은 domain의 포트에만 의존하므로, 포트 뒤의 구현체가 바뀌어도 유스케이스
  (`AnalyzeCallService`, `SimilarCaseSearchService` 등)의 코드는 안 바뀐다.
- 이건 "설계상 가능하다"는 주장이 아니라, 이 프로젝트에서 서로 다른 4개 축(판정
  알고리즘/검색 알고리즘/감사증적 저장소/딥보이스 판별기)에서 **각각 실제로 어댑터를
  교체했고, 매번 application 계층 diff가 0줄이었다**는 실측 결과다(위 표의 커밋 참고).
  "새 사기유형 추가"라는 N-06의 원래 시나리오도 같은 패턴(카테고리 enum + 규칙 dict
  확장)으로 이미 검증됐다.

### 확장성이 아직 검증 안 된 지점 (정직하게 밝힘)

- mcp-server의 REST 엔드포인트(`rest_server.py`)와 MCP stdio 엔드포인트(`server.py`)는
  같은 application 서비스를 재사용하지만, 진입점 자체의 배선 코드는 복붙돼 있다
  (`rest_server.py` 상단 주석: "공유 모듈로 뽑을 만큼 커지면 그때 리팩터링") — "새
  진입점 프로토콜 추가"(예: gRPC)는 아직 실제로 검증된 확장 축이 아니다.
- ~~N-02 RBAC은 apps/api에만 있고 mcp-server에는 없다~~ — 해결됨(2026-08-31). mcp-server
  REST 어댑터(`rest_server.py`)에도 동일한 `Role`/`role_satisfies` 계층을 도입해
  `/api/v1/analyze`·`/api/v1/reports`를 보호했다(`infrastructure/adapters/
  api_key_role_auth.py`, apps/api 것과 값·구조 모두 동일하게 복붙). apps/api는 서비스
  대 서비스 자격증명(`MCP_SERVICE_API_KEY`)으로 통과한다 — "접근권한 체계를 새 서비스에
  얹는" 확장도 이제 2곳(apps/api, mcp-server)에서 같은 패턴으로 검증됐다. 다만 MCP
  stdio 진입점(`server.py`)은 로컬 신뢰 실행 경로라 이 인증 대상에서 의도적으로
  제외했다 — "모든 진입점에 인증을 강제"까지 검증된 건 아니다.
- Prometheus 메트릭 네이밍(`vps_` 접두사)은 컨벤션 수준의 확장성이라 코드가 강제하지
  않는다 — 새 메트릭을 추가할 때 접두사를 빼먹어도 아무것도 막지 않는다.
- ~~F-03 딥보이스 판별기는 포트(`DeepvoiceDetectionPort`)만 준비돼 있고 아직 실제
  교체는 일어나지 않았다~~ — 해결됨(2026-08-31). HuggingFace Hub의 공개 스푸핑 탐지
  모델(wav2vec2 기반) 두 개를 F-03 실측 데이터셋(16건)에 직접 태워 비교한 뒤
  `Wav2Vec2DeepvoiceAdapter`(v2)를 기본값으로 교체했다(`wav2vec2_deepvoice_adapter.py`
  상단 주석 참고). 다만 이 교체로 새로 드러난 한계가 있다 — 첫 번째로 시도한 모델
  (ASVspoof 계열로 추정)은 재현율 3/8에 그쳤다(영어 스푸핑 위주 학습 데이터가 한국어
  gTTS 합성 음성에 일반화되지 않음). 채택한 두 번째 모델은 16건 전부를 신뢰도 0.99
  이상으로 정확히 분류했지만, 학습 데이터셋이 모델 카드에 명시돼 있지 않아 우리
  데이터셋과 겹칠 가능성을 배제할 수 없다 — "포트가 있다"에서 "실제로 교체해봤다"로는
  올라섰지만, "이 정확도가 일반화된다"는 아직 별개의 증명되지 않은 주장이다.
