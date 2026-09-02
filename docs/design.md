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

전체 스키마는 4개 테이블뿐이다(`infra/db/init.sql`) — `call_analysis_results`
(N-01, api 소유), `report_records`(N-01, mcp-server 소유), `fraud_cases`(F-04,
pgvector, rag-worker 소유), `channel_signals`(우선순위 2 크로스채널 상관관계 탐지,
2026-09-02 추가, mcp-server 소유). 상세 컬럼/제약조건/append-only 트리거 구현과, 왜
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

## 4. 배포 구조 (계획 — 실배포 전, 클라우드 사업자 전환 중)

> **2026-09-02 결정**: AWS EC2(t3.large)로 실제 인스턴스를 띄워 아래 4.1~4.5의
> 계획을 검증까지 해봤다 — Docker/Docker Compose 설치, 8개 컨테이너 전체
> healthy 기동, 호스트 Ollama(CPU) 연동, 실제 API 호출까지 전부 성공했고
> 그 과정에서 실배포로만 드러나는 버그 2건도 발견/수정했다(아래 "AWS EC2
> 실배포 실측 결과" 참고). 하지만 최종적으로는 **Oracle Cloud Always Free
> 티어로 전환하기로 결정**했다 — 포트폴리오 규모에서 t3.large는 24/7 기준
> 월 약 $60가 드는데, Oracle의 Always Free ARM 인스턴스(최대 4 OCPU/24GB
> RAM)를 쓰면 이 스택 전체를 컴퓨팅 비용 0원으로 상시 운영할 수 있다.
> AWS 인스턴스/보안그룹/키페어는 전환 결정 직후 정리(terminate)했다 — 아래
> 4.1~4.5는 사업자에 무관하게 그대로 적용되는 설계(Cloudflare Tunnel로
> 인바운드 포트 자체를 안 여는 방식 등)라 그대로 두고, Oracle Cloud 인스턴스
> 스펙 등 확정값은 실제로 만들 때 이 절을 교체한다.

### AWS EC2 실배포 실측 결과 (2026-09-02, 이후 Oracle Cloud로 전환)

- t3.large(2vCPU/8GB) + Ubuntu 24.04, 보안그룹은 SSH(관리자 IP만)만 개방, 나머지는
  4.1의 설계대로 인바운드 미개방 — `docker compose up --build`로 8개 컨테이너
  전부 healthy 확인, 호스트 Ollama(EXAONE 3.5 2.4B, CPU)까지 실제 기동.
- **버그 발견 1**: `docker-compose.yaml`의 mcp-server 서비스에 `RAG_WORKER_URL`
  환경변수가 아예 없어서, 어댑터 기본값(`http://localhost:8200`)이 컨테이너
  안에서는 mcp-server 자기 자신을 가리켜 F-04(유사사례 결합)가 모든
  docker-compose 배포(로컬 포함)에서 조용히 항상 빈 결과로 폴백하고 있었다 —
  실배포 전까지 아무도 눈치채지 못한 이유는 이 실패가 예외 없이 로그 경고만
  남기고 넘어가도록 설계돼 있어서다(`rag_worker_search_adapter.py` 참고). 서비스
  이름(`http://rag-worker:8200`)으로 고쳐서 해결.
- **버그 발견 2**: CPU 전용 인스턴스에서 EXAONE 2.4B 추론이 mcp-server의 LLM
  호출 타임아웃(20초)을 넘겨 규칙 기반(v1)으로 계속 폴백됐다(자동 폴백 자체는
  의도한 설계라 정상 동작이지만, "v2가 실제로 완료되는 경우"를 실측하려면
  타임아웃을 늘려야 했다). `OLLAMA_TIMEOUT_SECONDS`/`MCP_ANALYZE_TIMEOUT_SECONDS`
  환경변수를 새로 노출해 워밍업된 모델 기준 실제 추론 시간(약 54초, 콜드스타트는
  약 73초)까지 실측 확인 — 다만 배포에는 기본값(20초/30초)을 그대로 뒀다:
  73초까지 기다리는 것보다 20초 안에 v1으로 폴백하는 쪽이 데모 응답성 측면에서
  낫다고 판단(N-05 SLA 관점에서도 20초가 5초보다 이미 한참 느리지만, 73초보다는
  낫다).
- 이 두 수정은 클라우드 사업자와 무관한 코드/설정 버그라 커밋에 그대로 남아있고
  (Oracle Cloud로 배포해도 동일하게 적용됨), AWS 인스턴스 자체만 정리했다.

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
재현될 가능성이 높다.

**후속 조치(같은 날, `docs/test-plan.md` "N-05 동시성 SLA 해결 시도" 절)로
위 (a)를 실제로 구현하고 실측했다** — mcp-server/rag-worker의 REST
핸들러가 동기 블로킹 호출을 그대로 불러 이벤트 루프를 막던(우발적 전체
직렬화) 버그를 `run_in_threadpool`로 고치고, `asyncio.Semaphore`
(`LLM_MAX_CONCURRENCY`)로 동시 실행 개수를 명시적으로 제한했다. 결과는
꼬리 지연시간(p95/p99/최대)을 30~40% 개선했지만(최대 22.1초→11~14초대),
**평균 지연시간과 SLA 위반 비율은 거의 그대로였다** — 세마포어 값(1/2/4)도
결과에 거의 영향이 없었다. 이걸로 "진짜 병목이 소프트웨어(우발적
직렬화)인지 인프라(GPU 용량)인지"를 명확히 분리했다: **인프라다.** 남은
선택지는 GPU 용량 확충 또는 수요 측 속도제한/큐잉뿐이고, 둘 다 아직
미도입이다. `OLLAMA_KEEP_ALIVE`(콜드스타트 완화, 위 (b))는 이번 동시성
문제와는 별개 축이라 이번 실측 범위에서 다루지 않았다 — 콜드스타트는
"첫 요청이 느림", 동시성 문제는 "여러 요청이 몰리면 전부 느림"으로 서로
다른 증상이다.

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
infrastructure를 통째로 갈아끼우거나(알고리즘 교체, 저장소 교체) 새 진입점을
추가해도(새 카테고리, 새 프로토콜) 위쪽 계층은 파급을 받지 않는다.** 아래는 이게
이론이 아니라 이 프로젝트에서 **이미 7번 실제로 일어난 일**이라는 근거다.

### 확장 지점별 현황

| # | 무엇을 바꾸는 지점인가 | Port(인터페이스) | 현재 구현체 | 실제 교체 이력 | application 계층 diff |
|---|---|---|---|---|---|
| 1 | F-01/F-02 판정 알고리즘 | `CallAnalysisPort` | `RuleBasedCallAnalysisAdapter`(v1, 폴백용으로 유지) / `OllamaCallAnalysisAdapter`(v2, 기본값) | v1→v2 (커밋 `360ffde`) | 0줄 |
| 2 | F-04 유사사례 검색 알고리즘 | `FraudCaseSearchPort` | `TfidfSimilarityAdapter`(v1, 디버그 비교용) / `EmbeddingSimilarityAdapter`(v2) / `PgvectorSimilarityAdapter`(v3, 기본값) | v1→v2 (`2d60b87`), v2→v3 (`960e96e`) | 0줄 |
| 3 | N-01 감사증적 저장소 | `CallLogPort` / `ReportRepositoryPort` | `InMemory*`(테스트 전용) / `Postgres*`(운영) | InMemory→Postgres (`bd68902`) | 0줄 |
| 4 | F-03 딥보이스 판별기 | `DeepvoiceDetectionPort` | `HeuristicDeepvoiceAdapter`(v1, 폴백 겸 N-04 보조 지표용으로 유지) / `Wav2Vec2DeepvoiceAdapter`(v2, 기본값) | v1→v2 (2026-08-31, `wav2vec2_deepvoice_adapter.py`) | 0줄 |
| 5 | F-01 사기유형 카테고리 | `PatternCategory` enum + `PATTERN_RULES` dict | 4종(기관사칭/공포조성/긴급송금유도/개인정보요구) | 스캐폴딩 초기 커밋부터 4번째 카테고리를 "확장 예시"로 포함 | 0줄 |
| 6 | N-02 접근권한 역할 | `Role` enum + `role_satisfies` 계층 | VIEWER/HANDLER/ADMIN 3단계, apps/api·mcp-server 양쪽에 동일 구조 | apps/api 도입 → mcp-server로 확장(`c9799af`, 같은 패턴 복붙) | 0줄 |
| 7 | mcp-server 진입점 프로토콜 | (포트 아님 — 같은 `CallAnalysisService`를 감싸는 어댑터 3개) | REST(`rest_server.py`) / MCP stdio(`server.py`) / **gRPC(`grpc_server.py`, 2026-09-01 추가)** | REST+stdio 2개 → gRPC 3번째 추가. N-02 RBAC(`Role`/`API_KEYS`)도 grpc metadata로 재사용해 3번째 진입점까지 확장 | 0줄 |

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

- ~~mcp-server의 REST 엔드포인트(`rest_server.py`)와 MCP stdio 엔드포인트(`server.py`)는
  같은 application 서비스를 재사용하지만, "새 진입점 프로토콜 추가"는 아직 검증된
  확장 축이 아니다~~ — 해결됨(2026-09-01). gRPC를 3번째 진입점으로 추가해
  `CallAnalysisService`를 그대로 재사용했다(`grpc_server.py`, application/domain
  계층 diff 0줄, 위 표 7번). N-02 RBAC(`Role`/`API_KEYS`)도 grpc metadata(`x-api-key`)
  기반으로 재사용해, "접근통제까지 포함해 새 진입점을 추가할 수 있는가"까지 실제
  gRPC 클라이언트로 검증했다(`test_grpc_server.py` — 정상 호출/미인증/권한부족 3가지
  실측). 진입점 배선 코드 자체는 여전히 3곳에 복붙돼 있다(`rest_server.py` 상단 주석과
  같은 이유 — 공유 모듈로 뽑을 만큼 커지면 그때 리팩터링). 이 gRPC 진입점은 검증
  목적이라 docker-compose에는 아직 등록하지 않았다(README "mcp-server gRPC 진입점"
  참고) — "프로덕션 배포까지 완료"는 아니라는 점은 정직하게 남겨둔다.
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
  올라섰지만, "이 정확도가 일반화된다"는 아직 별개의 증명되지 않은 주장이었다.
  **일반화 검증 완료(2026-09-01)** — 보정 데이터셋(16건, TTS는 gTTS뿐이고 자연
  발화는 전부 영어)의 두 약점(엔진 1종만 검증, 언어가 갈려있어 "합성 여부가 아니라
  언어를 구분한 것 아니냐"는 교란 요인)을 통제한 별도 홀드아웃 48건(TTS: gTTS+
  edge-tts, 자연 발화: 영어 LibriSpeech+한국어 Zeroth-Korean)으로 재검증한 결과
  전체 47/48(97.9%) — 특히 처음 보는 엔진(edge-tts, 12/12)과 한국어 실제 발화
  (12/12) 양쪽 모두 완벽 분리했다. 여전히 48건 규모라 프로덕션 수준의 일반화까지
  보장하진 않지만, "gTTS 특유 아티팩트만 외웠다"/"언어를 구분했을 뿐이다"라는 두
  구체적 반박 가설은 실측으로 기각했다(`docs/test-plan.md` "F-03 v2 일반화 검증"
  절 참고).

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

## 7. 크로스채널 상관관계 탐지 (우선순위 2, 2026-09-02)

### 문제의식

시중 보이스피싱 차단 앱(에이닷 전화, 시티즌코난, 후후 등)은 전부 자기 채널 안에서만
판단한다 — 통화앱은 통화만, 메일 서비스는 메일만 본다. 반면 실제 보이스피싱은 "전화로
신뢰 형성 → 문자로 악성 링크 전송 → 이메일로 위장 공문 발송" 같은 다단계·다채널
공격으로 진화하고 있다. 이 프로젝트는 여러 채널을 한 기관이 운영하는 통합 시스템이라는
설정이므로, 채널을 넘나드는 연계를 탐지할 수 있다는 게 이 기능의 차별점이다.

### 설계

```
apps/mcp-server/src/
  domain/
    entity_extraction.py     # 텍스트 -> [전화번호|계좌번호|URL] 정규식 추출(정규화 포함)
    entities.py               # Channel/EntityType/ExtractedEntity/ChannelSignal/
                               # CorrelationMatch/CorrelationResult
    ports.py                  # ChannelSignalRepositoryPort
  application/services.py     # MultichannelCorrelationService
  infrastructure/adapters/
    postgres_channel_signal_repository.py   # channel_signals 테이블 구현체
  server.py / rest_server.py  # MCP 툴 correlate_multichannel_signals /
                               # REST POST /api/v1/correlate, analyze_call_pattern에 자동 결합
```

F-01/F-02/F-04와 같은 포트-어댑터 패턴을 그대로 따른다 — `MultichannelCorrelationService`는
`ChannelSignalRepositoryPort`만 알고, 실제 저장/조회(postgres)는 모른다.

**동작 순서**: `MultichannelCorrelationService.correlate(channel, entities, occurred_at, ...)`가
① 먼저 다른 채널에서 같은 엔티티가 시간 윈도우(기본 30분, 환경변수 없이 상수로 관리 —
이 규모에서 튜닝 여지가 크지 않다고 판단) 안에 기록된 적이 있는지 조회하고, ② 그 다음
이번 이벤트를 채널 신호로 기록한다(순서가 중요 — 자기 자신과는 매칭되지 않아야 한다).
매치가 있으면 건당 15점(상한 30점)을 위험도에 가산하고, F-02 등급(`risk_level_for_score`,
`domain/entities.py`)을 다시 매겨 F-05 판정 근거에 "N분 전 문자 채널에서 동일
계좌번호(마스킹됨)가 감지되었습니다" 식 문장을 추가한다. `CallAnalysisService.execute()`가
F-04(유사사례 결합) 다음 단계로 이 로직을 호출하도록 결합했다 — rag-worker와 마찬가지로
선택적 의존이라, correlation_service가 없거나 매치가 없으면 기존 판정 결과를 그대로
반환한다(N-04 관점에서도 breakdown과 별개로 `correlation_boost` 필드를 노출해 "이 점수
중 몇 점이 상관관계 때문인지" 계속 추적 가능하게 했다).

### 저장소: 왜 새 테이블이 필요했는가 (전제 정정)

이 기능의 원래 작업지시서는 "ERD의 `AUDIT_LOGS`가 이미 `entity_type`+`entity_id`로
모든 엔티티를 범용 참조하도록 설계되어 있으므로 조회 쿼리만 추가하면 된다"고 가정했다.
작업 착수 전 레포를 재검증한 결과 그런 파일(`docs/erd.md`)이나 범용 참조 컬럼은 실제로
존재하지 않았다 — `call_analysis_results`는 판정 결과 전용 컬럼(risk_score,
detected_patterns 등)만 가진 구체적인 스키마였다. 그래서 목적 전용 테이블
`channel_signals`(channel, entity_type, entity_value, occurred_at, context_excerpt)를
새로 추가했다 — 상세 컬럼/PK 설계는
[`jekyll/chapters/부록D-데이터베이스ERD.markdown`](../jekyll/chapters/부록D-데이터베이스ERD.markdown)
D.5b 참고.

이 정정 자체가 5장(N-06 확장성 설계)의 논의를 한 겹 더 명확하게 만든다: 지금까지의
확장 사례(판정 알고리즘 교체, 검색 알고리즘 교체, 감사증적 저장소 교체, gRPC 진입점
추가)는 전부 **애플리케이션 계층만 바꾸고 스키마는 그대로 두는** 확장이었다. 반면 이
기능은 "완전히 새로운 질의 축(엔티티 값으로 시간 윈도우 조회)"이 필요해서 **스키마
자체를 확장**해야 했다 — N-06이 "재설계 없는 확장"을 약속하는 건 전자의 범위이고,
후자(새로운 질의 패턴)는 정직하게 스키마 변경이 필요하다는 걸 이 사례가 보여준다.

### N-03(개인정보 마스킹)과의 상호작용 — 해소됨 (2026-09-02)

첫 이터레이션에서는 `apps/api`가 mcp-server를 호출하기 **전에** 통화 텍스트를
마스킹하는 것(전화번호/계좌번호가 `[전화번호]`/`[계좌번호]` 태그로 치환됨,
`apps/api/src/domain/pii_masking.py`) 때문에, REST 경로(`apps/api → apps/mcp-server`)
에서는 `analyze_call_pattern`이 받는 transcript 자체가 이미 마스킹된 뒤라 전화번호/
계좌번호 상관관계가 매칭되지 않는 한계가 있었다.

**해소 방식**: `apps/api`에 정규식 추출 모듈(`domain/entity_extraction.py`)을 새로
추가해, `mask_pii()`를 적용하기 **전** raw_transcript에서 먼저 엔티티를 추출한다.
mcp-server로는 원문 전체가 아니라 **추출된 엔티티 값만**(`entity_type`+`value`
목록) 보낸다 — `POST /api/v1/correlate`가 `text`(정규식 추출을 mcp-server가
대신 해주는 경로, Claude Code/합성 데이터 주입용)와 `entities`(이미 추출된 값,
apps/api용) 두 입력을 모두 받도록 확장했다(`domain/ports.py`의
`MultichannelCorrelationPort`, `infrastructure/adapters/mcp_correlation_adapter.py`).
이렇게 하면 raw_transcript 자체는 여전히 mcp-server로 나가지 않아(N-03의 핵심
목표 유지) 크로스채널 매칭에 필요한 최소한의 값만 전달된다.

`AnalyzeCallService.execute()`가 `/api/v1/analyze` 응답을 받은 뒤 이 흐름을
호출하고, 매치가 있으면 응답의 `risk_score`/`risk_level`을 갱신하고 근거 문장을
추가한다(`_merge_correlation_into_raw`). mcp-server 내부 결합(`CallAnalysisService`)
과 달리 summary 문장 전체를 재생성하지 않고, 원래 문장에 "(크로스채널 상관관계
+15점 반영, 최종 100점/고위험)" 식으로 덧붙이는 방식을 택했다 — 두 계층에 같은
등급 라벨/문장 템플릿을 중복 유지하지 않기 위함.

### 실측 검증

- 합성 시나리오 4건(`apps/mcp-server/data/synthetic_multichannel_signals.json`) —
  다단계 공격 연쇄(통화→12분 뒤 동일 계좌번호 문자→35분 뒤 동일 URL 이메일), 무관한
  채널 간 오탐 없음, 시간 윈도우(30분) 밖 배제, 윈도우 경계값(정확히 30분) 포함 여부까지
  `test_multichannel_synthetic_scenarios.py`로 검증.
- mcp-server REST 직접 호출로 종단 검증(2026-09-02): `/api/v1/correlate`로 문자
  채널에 계좌번호를 먼저 기록한 뒤, `/api/v1/analyze`로 같은 계좌번호가 포함된
  검찰 사칭 통화를 분석 — 기본 판정 65점이 상관관계 가산점 15점을 더해 80점(HIGH)
  으로 상승.
- **apps/api 경유(N-03 마스킹 포함) 종단 검증(2026-09-02)**: 같은 시나리오를
  `/api/v1/calls/analyze`(apps/api)로 호출 — 응답의 `masked_transcript`에
  `[계좌번호]` 태그가 정상적으로 찍혀 있는데도(N-03 마스킹이 여전히 적용됨을
  확인), risk_score가 95점→100점(상한, HIGH)으로 오르고 explanation_summary에
  "(크로스채널 상관관계 +15점 반영, 최종 100점/고위험)"이, explanation에 "0분
  전 문자 채널에서 동일 계좌번호(********9888)이(가) 감지되었습니다"가 실제로
  포함됨을 확인 — N-03 마스킹과 우선순위 2가 서로 상충하지 않고 함께 동작함을
  실측으로 증명했다.
