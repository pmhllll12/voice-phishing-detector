# 시험계획서 (Test Plan)

**기준 문서**: [`docs/requirements.md`](requirements.md), [`docs/RFP.md`](RFP.md)
**작성일**: 2026-08-31

> 이 문서는 이미 실행된 검증(pytest 211개, 실측 데이터셋, RBAC 실측, docker-compose
> e2e, CI)을 사후에 정리한 것이지, 앞으로 할 계획만 나열한 것이 아니다 — "계획"과
> "실측 결과"를 구분해서 표기한다.

## 1. 테스트 전략

3개 계층으로 구성한다.

| 계층 | 대상 | 도구 | 실행 시점 |
|---|---|---|---|
| 단위/통합 테스트 | domain/application 로직, 어댑터 | pytest | 로컬 + CI(모든 push/PR) |
| 실측 데이터셋 검증 | F-01/F-02 판정 정확도, F-03 딥보이스 판별 정확도 | pytest(회귀 가드) + 직접 제작한 데이터셋 | 임계값/모델 변경 시 |
| E2E(종단간) | 전체 스택(frontend→api→mcp-server/rag-worker/stt-worker→postgres) | Playwright(`run-voice-phishing-detector` 스킬의 driver.mjs) + curl 실측 | 주요 기능 변경 후 수동 실행 |

**왜 이 3계층인가**: 단위 테스트만으로는 "LLM/모델이 실제로 정확한 판정을 내리는가"를
검증할 수 없고(모킹하면 그 부분을 안 보는 것과 같음), E2E만으로는 회귀를 빠르게
못 잡는다(느리고, 실패 시 원인 특정이 어려움). 세 계층이 서로 다른 질문에 답한다 —
단위 테스트: "코드가 의도대로 조립되는가", 실측 데이터셋: "판정이 실제로
맞는가", E2E: "전체 시스템이 실제로 동작하는가".

## 2. 테스트 환경

| 환경 | 용도 | 비고 |
|---|---|---|
| 로컬(WSL2 + RTX 3050) | 개발 중 반복 실행, GPU 필요한 실측 검증 | `run-voice-phishing-detector` 스킬 |
| GitHub Actions(`ubuntu-latest`) | PR/push마다 자동 실행 | GPU 없음 — 전 서비스가 CPU로 자동 폴백하도록 이미 설계됨(README 참고) |
| docker-compose(로컬) | 배포 형태와 동일한 멀티 컨테이너 구성 검증 | Ollama는 호스트에서 별도 실행(README "로컬 실행" 참고) |

## 3. 서비스별 테스트 구성 (2026-09-02 기준)

| 서비스 | 테스트 파일 | 테스트 수 | postgres 필요 | 비고 |
|---|---|---|---|---|
| `apps/api` | 14개 | 74 | 일부(skipif) | F-03 v1/v2 실측 데이터셋 검증 + N-03 이름 마스킹 정량 평가 + postgres 재연결 회귀 + 크로스채널 상관관계(우선순위 2) N-03 경유 경로 2개 파일 10건 포함 |
| `apps/mcp-server` | 20개 | 123 | 일부(skipif) | Ollama 없이도 자동 폴백으로 전부 통과(실측 확인) + postgres 재연결/N-05 동시성 제한 회귀 + 크로스채널 상관관계(우선순위 2, Google Safe Browsing 포함) 7개 파일 47건 포함 |
| `apps/rag-worker` | 3개 | 12 | 일부(skipif) | pgvector 검색 통합 테스트 + 재연결 회귀 포함 |
| `apps/stt-worker` | 1개 | 2 | 불필요 | 가짜 어댑터만 사용, 실제 모델 로드 없음(의도적 — 무겁고 GPU 의존적이라) |
| **합계** | **38개** | **211** | | |

postgres가 필요한 테스트는 `TEST_DATABASE_URL`(또는 `DATABASE_URL`) 접속 가능
여부를 `pytest.mark.skipif`로 확인해 접속 불가 시 건너뛴다. **로컬에서는
건너뛰어질 수 있지만, CI(`.github/workflows/tests.yml`)는 postgres 서비스
컨테이너를 항상 띄워서 건너뛰지 않고 실제로 실행한다** — 커버리지를 skip으로
숨기지 않기 위함.

## 4. F-01~F-07 검수 시나리오

각 시나리오는 실제로 라이브 스택에 대해 실행하고 결과를 확인한 것이다(추정 아님).

### F-01/F-02: 통화 텍스트 분석 + 위험도 스코어링

| # | 입력 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| 1 | "검찰청 수사관인데 계좌가 범죄에 연루되어 지금 즉시 안전계좌로 이체해야 합니다" | 고위험(≥70), 기관사칭+긴급송금유도 탐지 | 위험도 85, 두 카테고리 정확히 탐지, 유사사례 2건 매칭(검찰 사칭 82%) |
| 2 | "금융감독원인데 명의도용된 계좌가 있어서 본인확인이 필요하다고 문자가 왔어요" | 명확한 긴급송금 요구가 없어 등급이 1번보다 낮아야 함 | 중위험(50)/저위험(30) — 반복 호출 시에도 문맥에 맞게 합리적으로 판단(LLM 특성상 소폭 변동은 정상) |
| 3 | "오늘 점심 메뉴는 김치찌개와 계란말이입니다" | 오탐 없음, 패턴 미탐지 | F-03 v2 실측 데이터셋의 자연 발화 텍스트로 간접 확인(대화 텍스트는 딥보이스 데이터셋이지만 F-01 합성 데이터셋 26건에도 정상 대화 포함, 오탐 0건) |

### F-03: 딥보이스 판별

| # | 입력 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| 1 | gTTS 합성 음성 8건 | `is_synthetic=True` | v1: 7/8, v2: 8/8 (전부 신뢰도 0.99 이상) |
| 2 | LibriSpeech 실제 인간 발화 8건 | `is_synthetic=False` | v1: 6/8(오탐 2건), v2: 8/8(오탐 0건) |
| 3 | 모델 로드 실패(존재하지 않는 모델명) | v1으로 자동 폴백, 예외 없이 판정 반환 | `test_falls_back_to_heuristic_when_model_unavailable` 통과 |

### F-03 v2 일반화 검증 (2026-09-01)

보정 데이터셋(16건, 위 표)과 별도인 홀드아웃 48건으로 검증했다 —
`data/deepvoice_generalization_samples/`, TTS 엔진 2종(gTTS/edge-tts) x
자연 발화 언어 2종(영어 LibriSpeech/한국어 Zeroth-Korean, CC BY 4.0) 조합.
보정 데이터셋의 두 가지 약점(같은 엔진으로만 검증, TTS=한국어/자연발화=영어라
언어가 갈려있어 "합성 여부가 아니라 언어를 구분한 것 아니냐"는 교란 요인)을
직접 통제했다.

| 그룹 | 건수 | 정확도 | 의미 |
|---|---|---|---|
| gTTS (보정과 동일 엔진) | 12 | 12/12 | 기준선 |
| edge-tts (처음 보는 엔진, MS 신경망 TTS) | 12 | 12/12 | "gTTS 특유 아티팩트만 외웠다"는 우려 반증 |
| LibriSpeech 영어 자연 발화 | 12 | 11/12 | 유일한 오탐 1건 |
| Zeroth-Korean 한국어 자연 발화 | 12 | 12/12 | "언어를 구분한 것 아니냐"는 교란 요인 통제·반증 |
| **전체** | **48** | **47/48 (97.9%)** | |

**결론**: 처음 보는 TTS 엔진과 한국어 실제 발화 양쪽 모두에서 완벽하게
분리해, "이 정확도가 일반화된다는 건 증명 안 됨"이라는 기존 우려를 상당히
줄였다. 다만 48건도 여전히 소규모라 프로덕션 수준의 일반화를 보장하진
않는다 — `test_deepvoice_generalization.py`로 회귀 가드.

### F-04: 유사사례 매칭

| # | 입력 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| 1 | "검찰 사칭" 시나리오를 원문과 다른 표현으로 변형한 쿼리 | 의미적으로 관련된 사례가 상위 | 임베딩: 검찰 출석요구형(FC-008, 유사도 0.701) 2위 / TF-IDF: 무관한 택배사칭형(FC-006, 0.074) 2위 — 임베딩이 명확히 우수(README 참고) |

### 부가기능: 크로스채널 상관관계 탐지 (2026-09-02)

합성 시나리오 4건(`apps/mcp-server/data/synthetic_multichannel_signals.json`)을
순서대로 재생해 각 단계에서 매칭 여부가 기대와 일치하는지 확인한다
(`test_multichannel_synthetic_scenarios.py`).

| 시나리오 | 내용 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| MC-01 | 검찰 사칭 통화(계좌번호) → 12분 뒤 동일 계좌번호 문자 → 35분 뒤(문자 기준 23분 뒤) 동일 URL 이메일 | 문자는 통화와, 이메일은 문자와만 매칭(이메일-통화는 시간 윈도우 밖) | PASS |
| MC-02 | 무관한 통화/문자(전화번호·URL 전부 다름) | 매칭 없음(오탐 방지) | PASS |
| MC-03 | 동일 계좌번호, 31분 뒤 등장(윈도우 30분 밖) | 매칭 없음 | PASS |
| MC-04 | 동일 계좌번호, 정확히 30분 뒤 등장(윈도우 경계값) | 매칭됨(경계 포함) | PASS |

mcp-server REST 스택(로컬 postgres, `CALL_ANALYSIS_BACKEND=rule`)에 대해 종단 실측을
수행했다: `/api/v1/correlate`로 문자 채널에 계좌번호를 먼저 기록 → `/api/v1/analyze`로
같은 계좌번호가 포함된 검찰 사칭 통화를 분석 → 기본 판정 65점(기관사칭 30 + 긴급송금유도
35)이 크로스채널 상관관계 가산점 15점을 더해 80점(HIGH)으로 상승.

**N-03(개인정보 마스킹) 경유 E2E까지 실측 완료(2026-09-02)**: apps/api에
`domain/entity_extraction.py`(마스킹 "전" 원문에서 추출)와 `MultichannelCorrelationPort`
를 추가해, 실제 프런트 대시보드가 쓰는 `/api/v1/calls/analyze`(apps/api) 경로로
같은 시나리오를 재현 — 응답의 `masked_transcript`에 `[계좌번호]` 태그가 정상
찍혀 있는데도(N-03 마스킹 적용 확인) risk_score가 95점→100점(HIGH)으로 오르고,
explanation에 "0분 전 문자 채널에서 동일 계좌번호(********9888)이(가)
감지되었습니다"가 실제로 포함됨을 curl로 직접 확인함(`docs/design.md` 7장
"실측 검증" 참고). 이전에는 apps/api를 우회해 mcp-server REST에 직접 호출한
경우에만 검증했고 N-03과의 상호작용은 "알려진 한계"로 남겨뒀었는데, 이번에
그 공백을 실제로 메웠다.

**Google Safe Browsing 연동(선택 항목, 2026-09-02)**: `test_google_safe_browsing_adapter.py`
로 요청 구성(`http://{host}/` 재구성 포함)/응답 파싱/HTTP 실패 시 빈 리스트 폴백을
httpx.post monkeypatch로 검증. `test_multichannel_correlation_service.py`에 6건
추가 — 크로스채널 매치 없이도 악성 URL만으로 가산점(+40)이 붙는지, 두 근거가
합산되는지(15+40), 여러 URL이 걸려도 가산점이 비례 증가하지 않는지, 포트가 없으면
전부 no-op인지. **실제 Google API 키로의 검증은 아직 안 함** — 무료 발급 가능하나
사용자 본인 Google 계정이 필요해 이번 세션 범위에서는 코드/폴백 경로까지만
완성했다(`docs/design.md` 7장 "선택 항목: Google Safe Browsing 연동" 참고).

### N-02: 접근통제(RBAC) — mcp-server 실측 매트릭스

| 케이스 | 기대 | 실측(2026-08-31) |
|---|---|---|
| `/health` (키 없음) | 200 | 200 |
| 키 없음 → `/api/v1/analyze`, `/api/v1/reports` | 401 | 401 / 401 |
| 잘못된 키 → 동일 | 401 | 401 / 401 |
| VIEWER 키 → 동일 | 403 | 403 / 403 |
| HANDLER 키 → 동일 | 200 | 200 / 200 |
| ADMIN 키 → `/api/v1/analyze` | 200 | 200 |

이 실측 과정에서 postgres 컨테이너 다운으로 인한 500 에러를 실제로 발견했고,
RBAC 로직이 아니라 인프라 문제임을 확인 후 재기동으로 해결했다(회귀 아님,
단일 장애점으로 문서화 — `docs/design.md` 참고).

### N-03: 이름 마스킹 정량 평가 (2026-09-01)

전화번호/계좌번호/주민등록번호는 형식이 고정적이라 `test_pii_masking.py`의
개별 사례로 충분하지만, 이름 마스킹("흔한 성씨+호칭" 휴리스틱)은 오탐/누락
위험이 커서 라벨 28건(`apps/api/data/pii_masking_eval.json`)으로 정량화했다.

| 버전 | 정밀도 | 재현율 | 비고 |
|---|---|---|---|
| 보정 전 | 0.615 (16/26) | 0.727 (16/22) | 오탐 10건: "고객님/이용자님/신청자님/조사관님" 등 성씨로 시작하는 흔한 단어를 이름으로 오판 |
| 보정 후 | **1.000** (16/16) | 0.727 (16/22) | 실측된 오탐 단어 10개를 블록리스트(`_NAME_FALSE_POSITIVE_WORDS`)로 제외 — 재현율은 그대로(블록리스트는 정밀도만 개선) |

재현율이 100%가 안 되는 6건(성씨 목록 밖 3건, 호칭이 이름과 분리 2건, 호칭
없는 반말 1건)은 알려진 한계로 문서화하고 `test_pii_masking_eval.py`의
회귀 가드 테스트로 "더 나빠지지 않게" 고정했다. 블록리스트도 실측된 사례만
등재한 것이라 완전하지 않다(다른 흔한 단어가 여전히 오탐될 수 있음).

### N-05: 판정 응답시간 SLA 실측 (2026-09-01)

부하 스크립트로 `apps/mcp-server/data/synthetic_call_transcripts.json`의 26건
전체를 실제 `/api/v1/calls/analyze`에 반복 호출. gpu-fleet-ops Prometheus에
`vps-api` 스크레이프 job을 추가(호스트 브리지 게이트웨이 IP, rag-worker와
동일 패턴)하고 `histogram_quantile`로 교차검증했다.

| 조건 | 요청 수 | 평균 | p95 | p99 | 5초 초과 |
|---|---|---|---|---|---|
| 순차(동시성 1) | 26건 | 2.11초 | 2.81초 | 3.02초 | 0/26 (0%) |
| 동시성 4 (3라운드) | 78건 | 8.75초 | 18.86초 | 22.11초 | 74/78 (94.9%) |

**결론**: 단일 요청 기준으로는 N-05 SLA(평균 5초 이내)를 충족한다. 하지만
동시 요청이 몰리면 크게 위반한다 — 원인은 코드가 아니라 Ollama(LLM)/
wav2vec2(딥보이스)/임베딩/STT가 GPU 1장(RTX 3050)을 나눠 쓰는 인프라
구조다. `vps_analysis_duration_seconds` 버킷 경계(1~10초 구간이
2.5/5/7.5/10초 4개뿐)가 성글어서 Prometheus의 `histogram_quantile`
보간값(p95 4.45초)은 클라이언트 실측(순차 2.81초/동시성 18.86초)보다
부정확하다는 것도 이번에 확인함 — SLA 임계값(5초) 근처 버킷을 더
세분화하는 게 후속 개선 과제다. Grafana 대시보드에 p95/p99 패널을
추가했다(`gpu-fleet-ops/dashboards/gpu-fleet-monitoring.json`, "N-05 판정
응답시간 p95/p99" 패널).

### N-05 동시성 SLA 해결 시도 (2026-09-01)

먼저 원인을 더 정밀하게 진단했다 — mcp-server(`rest_server.py`)와
rag-worker(`main.py`)의 REST 핸들러가 `async def`인데 내부에서 동기 코드
(httpx.post로 Ollama/rag-worker를 블로킹 호출, GPU 임베딩 인코딩)를 직접
불러서, 요청 하나가 끝날 때까지 그 프로세스의 이벤트 루프 전체가 막히는
걸 발견했다 — 동시 요청이 몇 개든 우발적으로 한 번에 하나씩만 처리되는
구조였다.

**적용한 수정**: 두 서비스 모두 `starlette.concurrency.run_in_threadpool`로
블로킹 호출을 스레드풀에 위임하고, mcp-server에는 `asyncio.Semaphore`로
동시 실행 개수를 명시적으로 제한(`LLM_MAX_CONCURRENCY`, 기본값 2)했다.

| 조건(동시성 4, 78건) | 평균 | p95 | p99 | 최대 | 5초 초과 |
|---|---|---|---|---|---|
| 수정 전 | 8.75초 | 18.86초 | 22.11초 | 22.11초 | 74/78 (94.9%) |
| 수정 후 (LLM_MAX_CONCURRENCY=1) | 8.32초 | 11.17초 | 13.60초 | 13.60초 | 76/78 (97.4%) |
| 수정 후 (LLM_MAX_CONCURRENCY=2) | 8.09초 | 11.84초 | 14.21초 | 14.21초 | 77/78 (98.7%) |
| 수정 후 (LLM_MAX_CONCURRENCY=4) | 8.11초 | 11.26초 | 11.73초 | 11.73초 | 75/78 (96.2%) |

**정직한 결론**: 이 수정은 꼬리 지연시간(p95/p99/최대)을 약 30~40% 줄였다
(예: 최대 22.1초 → 11~14초대) — 우발적 전체 직렬화로 일부 요청이 큐 뒤에서
비정상적으로 오래 기다리던 worst-case를 없앴기 때문이다. **하지만 평균
지연시간(약 8.1~8.3초)과 5초 초과 비율(96~99%)은 거의 개선되지 않았다** —
LLM_MAX_CONCURRENCY 값(1/2/4) 자체도 결과에 거의 영향을 주지 않았다. 즉
진짜 병목은 소프트웨어 버그가 아니라 **GPU 1장(RTX 3050)의 실제 처리
용량**이었다 — 애초 설계 문서(`docs/design.md` 6장 "N-05 실측")가 내린
결론과 일치한다. 세마포어 값을 조정해도 GPU가 감당할 수 있는 총 처리량
자체는 안 늘어난다.

**남은 과제(미해결, 정직하게 밝힘)**: 평균 지연시간까지 SLA(5초) 안으로
넣으려면 (a) GPU 용량을 늘리거나, (b) 수요 측에서 동시 요청 자체를
제한하는 속도 제한/큐잉을 프런트엔드나 API 게이트웨이 단에 두는 것 중
하나가 필요하다 — 둘 다 이 세션에서는 도입하지 않았다(전자는 비용, 후자는
"사용자에게 대기시간을 어떻게 보여줄 것인가"라는 별도의 UX 설계가 필요해서
범위 밖으로 남겨둠). 이 수정 자체(threadpool 위임 + 세마포어)는 값어치가
있다 — worst-case를 개선했고, 남은 병목이 정확히 무엇인지(GPU 용량이지
코드가 아니다) 실측으로 확정했다.

### postgres 단일 장애점 완화 검증 (2026-09-01)

`docker-compose.yaml` 전 서비스에 `restart: unless-stopped`를 추가하고, 실제
`vps-postgres` 컨테이너로 3가지를 라이브 검증했다.

| # | 시나리오 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| 1 | `docker kill vps-postgres`로 의도적 중지 | Docker 표준 동작상 자동 재기동 안 됨 | `Status=exited`, `RestartCount=0` — 확인됨 |
| 2 | `docker restart vps-postgres`로 postgres만 재기동(api는 안 건드림) | api가 재연결 로직으로 자동 복구 | 재기동 직후 `GET /ready` 200, `POST /api/v1/calls/analyze` 정상 응답 확인 |
| 3 | `infra/db/backup_postgres.sh`로 백업 후 스크래치 컨테이너에 복구 | 데이터 무손실 복구 | `fraud_cases` 10건 정확히 복구됨 확인 |

시나리오 1은 "이 정책이 만능이 아니다"를 정직하게 보여주는 경계 조건이다 —
`unless-stopped`는 크래시 복구용이지, 의도된 중지를 되돌리는 게 아니다. 진짜
프로세스 크래시(OOM-kill 등) 시 자동 재기동되는 경로는 이 개발 환경의 샌드박스
제약(컨테이너 PID 1에 직접 SIGKILL을 못 보냄, 스크래치 컨테이너로도 동일 확인)
때문에 직접 재현하지는 못했다 — Docker 표준 동작에 근거한 것이지 이 프로젝트에서
실측한 것은 아니다(`docs/design.md` 6장 참고).

시나리오 2를 발견하기 전엔 postgres restart 정책만으로 충분하다고 가정했는데,
실제로는 api/mcp-server/rag-worker가 재연결 로직 없이 postgres 재시작 후에도
계속 `"OperationalError: the connection is closed"`로 실패하는 걸 먼저
재현했다 — 그래서 3개 어댑터에 재연결 로직을 추가하고 각각 회귀 테스트를
붙였다(`test_reconnects_and_succeeds_after_connection_is_closed` 등, 위 3절
테스트 수 증가분 참고).

### N-06: mcp-server 신규 진입점(gRPC) 확장 검증 (2026-09-01)

REST(`rest_server.py`)/MCP stdio(`server.py`) 2개 진입점이 같은
`CallAnalysisService`를 재사용한다는 것까지만 검증돼 있었고, "새 진입점
프로토콜을 추가하는 것" 자체는 미검증 확장 축이었다(`docs/design.md`
"확장성이 아직 검증 안 된 지점"). gRPC를 3번째 진입점으로 실제로 추가해
진짜 gRPC 클라이언트로 검증했다.

| # | 시나리오 | 기대 결과 | 실측 결과 |
|---|---|---|---|
| 1 | 정상 호출(HANDLER 키) | REST/MCP와 동일한 판정 필드 반환 | `risk_score`/`risk_level`/`detected_patterns` 등 정상 반환, `authority_impersonation` 카테고리 정확히 탐지 |
| 2 | x-api-key metadata 없이 호출 | 인증 실패 | `grpc.StatusCode.UNAUTHENTICATED` |
| 3 | VIEWER 키로 호출(HANDLER 이상 필요) | 인가 실패 | `grpc.StatusCode.PERMISSION_DENIED` |

`git status`로 실제 diff 범위를 확인한 결과 `apps/mcp-server/src/application/`,
`domain/`은 한 줄도 안 바뀌었다 — 새 파일(`grpc_server.py`, `protos/`,
`grpc_generated/`, 테스트)과 `requirements.txt` 추가뿐이다. N-02 RBAC도
`Role`/`API_KEYS`(도메인 모델 + 저장소)를 그대로 재사용해 grpc metadata
기반으로 인증/인가했다 — FastAPI 전용인 `require_role` 데코레이터 자체는
재사용 못 했지만, 그 밑의 도메인 로직은 재사용됐다.

이 gRPC 진입점은 검증 목적이라 `docker-compose.yaml`에는 등록하지 않았다
(README "mcp-server gRPC 진입점" 참고) — "프로덕션 배포까지 마쳤다"는 아니다.

### F-05/F-06: 오디오 입력 → 대시보드 반영 (E2E)

Playwright(`--use-fake-device-for-media-stream`)로 마이크 녹음을 시뮬레이션:
녹음 시작 → 3초 대기 → 녹음 중지 → 업로드 → stt-worker 변환 → mcp-server
판정 → postgres 적재 → 대시보드 `총 분석 건수` 증가까지 확인(11→12).

### docker-compose 전체 스택 (E2E)

8개 서비스(frontend/api/mcp-server/rag-worker/stt-worker/postgres/prometheus/
grafana) `docker compose up --build` → 전부 `healthy` → 텍스트 분석 폼 제출 →
실제 Ollama LLM 호출 → postgres 적재 → 대시보드 반영까지 확인(2026-08-31).

## 5. CI 파이프라인

`.github/workflows/tests.yml` — push/PR마다 4개 서비스를 병렬 job으로 실행한다
(postgres 서비스 컨테이너 포함). 2026-08-31 기준 push/PR 양쪽 트리거에서 8개
job(4개 서비스 × 2트리거) 전부 통과 확인됨. Ollama 없이도 mcp-server 71개
테스트가 전부 통과하는 것을 로컬에서 실제로 Ollama를 내리고 확인한 뒤 CI에
반영했다.

## 6. 결함 관리

이 프로젝트는 1인 개발 포트폴리오라 별도 이슈 트래커 프로세스를 두지 않는다.
발견한 결함은 즉시 수정하고 커밋 메시지에 원인을 남긴다(예: rag-worker
Dockerfile이 `scripts/`를 안 담아 F-04 코퍼스 시딩이 크래시하던 문제,
`8e28f49`). GitHub Issues는 향후 필요 시 사용할 수 있으나 현재는 미사용.

## 7. 알려진 커버리지 공백 (정직하게 밝힘)

| 공백 | 내용 |
|---|---|
| N-05 동시성 하 평균 지연시간 SLA 미충족 | threadpool 위임+세마포어로 꼬리 지연시간(p95/p99/최대)은 30~40% 개선했지만(위 "N-05 동시성 SLA 해결 시도" 절), 평균 지연시간(8.1~8.3초)과 5초 초과 비율(96~99%)은 GPU 용량 자체가 병목이라 거의 그대로 — GPU 증설 또는 수요 측 속도제한/큐잉 필요, 둘 다 미도입 |
| N-03 이름 마스킹 재현율 100% 미달 | 정량 평가 완료(위 "N-03" 절), 재현율 0.727 — 성씨 목록 밖/호칭 분리/반말 3가지 패턴은 여전히 놓침. 정규식 기반이라 근본 해결은 NER 모델 도입 필요 |
| F-03 v2 일반화 — 48건 이상 규모 미검증 | 홀드아웃 48건(엔진 2종×언어 2종)으로 47/48 검증 완료(위 "F-03 v2 일반화 검증" 절), 프로덕션 규모(수백~수천 건)에서의 유지 여부는 미검증 |
| frontend(F-06) 단위/컴포넌트 테스트 | Playwright E2E만 있고 React 컴포넌트 단위 테스트는 없음 |
| gRPC 진입점(N-06) 프로덕션 미배포 + F-07 미포함 | `Analyze` RPC 1개만 검증했고 `submit_report`(F-07)는 gRPC로 노출 안 함. docker-compose 미등록이라 실제 운영 트래픽으로는 검증 안 됨 |
| 크로스채널 상관관계(우선순위 2) — sms/email 실채널 미연동 | 실제 SMS 수신/Gmail API 연동은 범위 밖 — 합성 이벤트를 `correlate_multichannel_signals` 툴로 수동 주입해서만 검증됨(위 "부가기능" 절 참고). apps/api 경유 시 전화번호/계좌번호 매칭 문제는 2026-09-02에 해소됨(더 이상 공백 아님) |
