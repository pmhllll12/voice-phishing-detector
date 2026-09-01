# 설계서 (System Design)

> **진행 상황**(2026-09-01 갱신): 시스템 아키텍처/데이터 모델/API 명세/N-06 확장성
> 챕터에 이어 **배포 구조(4장)도 계획 수준으로 채웠다** — 아직 실제 EC2 배포는
> 하지 않았으므로(`docker-compose.yaml` 로컬 실기동까지만 완료, README "진행 현황"
> 참고) 인스턴스 스펙 등 세부값은 "미확정"으로 남겨뒀다. 실제로 배포하면 확정값으로
> 교체한다.

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

## 4. 배포 구조 (계획 — 실배포 전)

> 아직 EC2에 올리지 않았다. 이 챕터는 gpu-fleet-ops에서 검증한 패턴을 이
> 프로젝트의 서비스 구성(`docker-compose.yaml`)에 맞춰 재적용하는 **계획**이다.
> 실제로 배포하면 인스턴스 스펙·도메인 등 확정값으로 이 절을 교체한다.

### 4.1 왜 인바운드 포트를 하나도 열지 않는가

일반적인 "EC2 + Nginx" 구성은 보안그룹에서 80/443을 전체(`0.0.0.0/0`)에
열어야 한다. Cloudflare Tunnel(`cloudflared`)은 반대로 **EC2 → Cloudflare
엣지로의 아웃바운드 연결만** 맺고, 인바운드는 그 터널을 타고 들어온다. 즉
보안그룹은 SSH(22, 관리자 IP만) 하나만 열면 되고 80/443은 아예 닫아둘 수
있다 — 인터넷에서 EC2로 직접 도달 가능한 경로 자체가 없으므로 N-02 RBAC이
막는 것과 별개로 공격 표면이 한 단계 더 줄어든다. gpu-fleet-ops에서 검증한
핵심이 이 부분이라, 이번에도 그대로 재사용한다.

### 4.2 EC2 인스턴스 스펙 (검토 중, 미확정)

이 스택의 서비스별 리소스 특성:

| 서비스 | 리소스 특성 |
|---|---|
| mcp-server → Ollama (EXAONE 3.5 2.4B Q4_K_M) | LLM 추론 — GPU면 지연시간 개선, CPU도 동작은 함(느림) |
| api → wav2vec2 딥보이스 모델 | 94.6M 파라미터, 실측 CPU 추론 0.54초/건(콜드스타트 2.47초) — CPU로 충분(F-03 v2 서빙 메트릭 항목 참고) |
| rag-worker → sentence-transformers 임베딩 | 코퍼스 10건 규모, CPU로 충분 |
| stt-worker → faster-whisper | CTranslate2 int8, GPU 있으면 활용하지만 CPU 폴백도 지원 |
| postgres+pgvector | 코퍼스/감사증적 규모가 작아 범용 인스턴스로 충분 |

즉 GPU가 필수인 건 Ollama뿐이고, 나머지는 이미 CPU 폴백이 실측 검증돼
있다. 포트폴리오 비용 제약을 고려하면:

- **1안(비용 우선)**: CPU 인스턴스(`t3.xlarge` 급, vCPU 4/메모리 16GB
  전후) + Ollama도 CPU로 — LLM 응답 지연이 늘어나는 대신 GPU 인스턴스
  대비 시간당 비용이 크게 낮다. N-05 메트릭(`vps_analysis_duration_seconds`)
  으로 실측해 SLA(5초 이내) 충족 여부를 배포 직후 확인한다.
- **2안(지연시간 우선)**: GPU 인스턴스(`g4dn.xlarge` 급, T4) — Ollama
  지연시간은 개선되지만 상시 기동 비용이 1안보다 높다.

**결정은 배포 시점에 1안으로 먼저 켜보고 N-05 실측치가 SLA를 못 채우면
2안으로 전환**하는 순서로 한다 — 두 옵션 다 `DeepvoiceDetectionPort` /
`CallAnalysisPort`처럼 인스턴스 교체만으로 끝나고 애플리케이션 코드 변경이
필요 없으므로(컨테이너가 CUDA 가용 여부를 런타임에 자동 감지) 전환 비용이
낮다.

**로컬 실측(2026-09-01, `docs/test-plan.md` "N-05" 절)이 이 선택에 실제
근거를 더했다**: 순차 요청은 평균 2.11초로 SLA를 넉넉히 충족하지만, 동시
요청 4건에서는 평균 8.75초(94.9%가 5초 초과)로 크게 위반했다 — 로컬
GPU(RTX 3050) 1장을 Ollama/wav2vec2/임베딩/STT가 나눠 쓰는 구조라 동시
추론이 몰리면 서로 대기한다. 즉 **GPU를 붙인다고 이 문제가 자동으로
풀리지 않는다** — 2안(GPU 인스턴스)도 GPU가 1장뿐이면 동일한 경합이
재현될 가능성이 높다. 실제 배포 시엔 인스턴스 타입 선택과 별개로 (a)
mcp-server 앞에 동시 LLM 호출 수를 제한하는 세마포어/큐를 두거나, (b)
Ollama에 `OLLAMA_KEEP_ALIVE`로 모델을 상시 로드해 콜드스타트를 줄이는 것
중 하나를 먼저 검토해야 한다 — 인스턴스 스펙만으로 해결할 문제가 아니라는
게 이번 실측의 핵심 결론이다.

### 4.3 서비스별 공개 범위

`docker-compose.yaml`의 7개 서비스 중 인터넷에 실제로 노출해야 하는 건
2개뿐이다 — 나머지는 서비스 간 통신만 필요하다.

| 서비스 | 포트 | 공개 범위 |
|---|---|---|
| frontend | 3000 | **공개** — Cloudflare Tunnel로 `app.<domain>` 연결 |
| api | 8000 | **공개** — 프런트가 브라우저에서 직접 호출 + 모바일 앱(F-05 오디오 업로드)이 호출할 경로라 `api.<domain>`으로 별도 연결 |
| mcp-server | 8100 | 비공개 — api만 호출(N-02 서비스 자격증명), 터널에 연결 안 함 |
| rag-worker | 8200 | 비공개 — mcp-server만 호출 |
| stt-worker | 8300 | 비공개 — api만 호출 |
| postgres | 5432 | 비공개 — 도커 브리지 네트워크 내부만, 프로덕션에서는 호스트 포트 매핑 자체를 제거 |
| grafana | 3001 | 비공개(관리자 전용) — Cloudflare Access(이메일 인증)로 보호한 `grafana.<domain>`, 일반 공개 터널과 분리 |
| prometheus | 9090 | 비공개 — grafana만 조회, 외부 노출 안 함 |

이 표는 N-02 RBAC이 "인증된 사용자 중 누가 무엇을 할 수 있는가"를 막는
것과 별개로, "애초에 인터넷에서 도달 가능한 서비스가 몇 개인가"를 줄이는
계층이다 — 두 통제가 겹치는 게 아니라 서로 다른 위협을 막는다(RBAC은
탈취된 자격증명, 공개 범위 축소는 미인증 스캐닝/취약점 익스플로잇).

### 4.4 Nginx 리버스 프록시 + TLS

`cloudflared`가 EC2 안에서 로컬 Nginx로 트래픽을 넘기고, Nginx가 호스트명
기준으로 각 컨테이너 포트에 매핑한다:

```
Cloudflare 엣지 (공개 도메인, Full(strict) SSL)
   │  (아웃바운드 터널)
cloudflared (EC2 내부, 인바운드 포트 불필요)
   │
Nginx (EC2 로컬, 127.0.0.1 또는 도커 브리지 게이트웨이만 수신)
   ├─ app.<domain>     → frontend:3000
   ├─ api.<domain>     → api:8000
   └─ grafana.<domain> → grafana:3001 (+ Cloudflare Access)
```

Cloudflare "Full(strict)" 모드는 엣지↔오리진 구간도 유효한 인증서를
요구하므로, Nginx에는 Cloudflare Origin CA 인증서(무료, Cloudflare가
발급)를 설치한다 — Let's Encrypt처럼 갱신을 별도로 관리할 필요 없이
Cloudflare 대시보드에서 발급/갱신한다는 게 이 조합을 재사용하는 이유다.

### 4.5 배포 절차 (계획)

1. EC2 인스턴스 생성 (4.2의 1안으로 시작), 보안그룹은 SSH만 관리자 IP로 제한
2. Docker + Docker Compose 설치, 이 저장소 clone
3. `.env.example` → `.env`로 복사 후 운영값 채움 (API 키, DB 비밀번호,
   `MCP_SERVICE_API_KEY` 등 — N-02/N-03 문서 참고)
4. `docker compose up -d --build`, 전 서비스 `/health`·`/ready` 확인
5. `cloudflared` 설치 + 터널 생성, DNS 레코드(`app.`/`api.`/`grafana.`)를
   터널에 연결
6. Nginx 설정 + Cloudflare Origin CA 인증서 설치
7. N-05 메트릭으로 실트래픽 기준 SLA(5초 이내) 확인 — 배포 후 가장 먼저
   검증할 항목(README/test-plan.md에 이미 "알려진 커버리지 공백"으로
   명시돼 있던 부분)

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

## 6. postgres 단일 장애점 완화 (2026-09-01)

postgres가 죽으면 N-01(감사증적)·F-04(유사사례 검색)가 전부 멈춘다 — api/mcp-server/
rag-worker 모두 postgres 하나에 의존하는 단일 장애점이다. 아래 3가지를 실제로
적용/실측했다.

### 6.1 프로세스 크래시 자동 복구 — `restart: unless-stopped`

`docker-compose.yaml`의 모든 서비스(postgres 포함)에 `restart: unless-stopped`를
추가했다. **실측으로 확인한 중요한 경계선**: 이 정책은 "프로세스가 죽으면 다시
켠다"이지 "누가 멈춘 걸 되돌린다"가 아니다 — 로컬 `vps-postgres` 컨테이너에 이
정책을 걸고 `docker kill`로 직접 꺼봤더니 `RestartCount=0`, `Status=exited`로
**자동 재기동되지 않았다**(Docker의 표준 동작 — `docker stop`/`docker kill`처럼
의도된 중지는 재시작 정책이 무시한다). 반대로 정말 예기치 않게 프로세스가
죽는 경우(OOM-kill 등)엔 이 정책이 그대로 살아난다 — 다만 이 개발 환경(샌드박스화된
WSL2 docker)에서는 컨테이너 내부 PID 1에 직접 SIGKILL을 보내는 것 자체가 막혀 있어
그 경로까지는 실측하지 못했다(스크래치 컨테이너로도 동일하게 재현 안 됨을 확인해,
vps-postgres 고유의 문제가 아니라 이 샌드박스의 제약임을 확인함). "의도된 중지엔
재시작 안 함" 쪽은 실측 검증 완료, "진짜 크래시엔 재시작함" 쪽은 Docker 표준 동작에
근거한 것이지 이 환경에서 직접 재현하진 못했다 — 정직하게 구분해서 밝힌다.

### 6.2 애플리케이션단 재연결 — 더 중요한 발견

**restart 정책만으로는 부족했다.** postgres가 재기동돼도 api/mcp-server/rag-worker가
들고 있던 psycopg 연결 객체는 여전히 끊긴 채로 남는다 — 실제로 `docker restart
vps-postgres` 후 api를 건드리지 않고 `/ready`를 호출해보니 `"OperationalError: the
connection is closed"`로 계속 실패했다(api를 수동 재시작해야만 복구됐음). 즉
postgres 자체의 가용성을 아무리 개선해도, 그걸 쓰는 3개 서비스가 재연결을 못 하면
장애가 그대로 지속된다 — restart 정책 하나만으로는 이 장애점이 완화되지 않는다는
뜻이다.

그래서 `PostgresCallLogRepository`(apps/api), `PostgresReportRepository`
(mcp-server), `PgvectorSimilarityAdapter`(rag-worker) 3곳 전부에 동일한 패턴을
추가했다 — 쿼리가 `psycopg.OperationalError`로 실패하면 연결을 버리고 한 번
재연결해 재시도한다(pgvector 쪽은 재연결한 커넥션에 `register_vector`도 다시
건다). 라이브로 검증: api를 재시작하지 않은 채 `docker restart vps-postgres`만
실행하고 곧바로 `/ready`와 `POST /api/v1/calls/analyze`를 호출해 둘 다 정상
응답하는 것까지 확인했다. 각 서비스에 회귀 가드 테스트도 추가했다(연결을 강제로
닫고 다음 호출이 재연결 후 성공하는지 확인).

커넥션 풀링(예: psycopg_pool)까지는 도입하지 않았다 — 지금 규모(uvicorn 단일
워커, 요청이 사실상 직렬화됨)에서 풀은 복잡도만 늘리고 실익이 적다고 판단했다.
연결이 여러 개 필요해질 정도로 동시 요청이 늘어나면(N-05 SLA 절의 동시성 문제와
같은 방향의 확장) 그때 재검토할 항목이다.

### 6.3 데이터 자체의 보존 — 백업/복구

restart 정책은 볼륨 손상이나 실수로 인한 데이터 삭제는 못 막는다. `infra/db/
backup_postgres.sh`(pg_dump + gzip, 보관 기간 지난 백업 자동 정리)를 추가하고
**실제로 백업→복구 왕복까지 검증**했다 — `vps-postgres`에서 백업을 뜬 뒤, 별도
스크래치 postgres 컨테이너에 복구해서 `fraud_cases` 10건이 그대로 돌아오는 것까지
확인했다. 이 스크립트를 cron/systemd timer에 등록하는 건 배포 환경마다 방식이
달라 이 저장소엔 스케줄 등록까지는 하지 않았다(README "postgres 백업/복구" 절에
등록 예시만 남김).

### 아직 안 한 것 (정직하게 밝힘)

- **복제(replica)/자동 페일오버**: 단일 인스턴스 규모에서 두 번째 postgres를
  상시 운영하는 비용/복잡도가, "재기동 자동화 + 백업"으로 얻는 가용성 개선 대비
  과하다고 판단해 도입하지 않았다. 인스턴스 자체가 아예 사라지는 장애(디스크
  고장 등)는 여전히 백업 복구(RPO는 백업 주기만큼, 수동 트리거)로만 대응한다 —
  RTO/RPO를 수치로 약속할 수 있는 수준은 아니다.
- 진짜 프로세스 크래시(OOM-kill 등) 시 `restart: unless-stopped`가 실제로
  작동하는지는 이 개발 환경의 샌드박스 제약으로 직접 재현하지 못했다(6.1 참고) —
  Docker 표준 동작에 근거한 것이지 이 프로젝트에서 실측한 것은 아니다.
