# 역방향 신원확인 POC (모의 시제품)

> **고지**: 이 문서와 `apps/verify-worker`는 「2026 모바일신분증 아이디어 공모전」에 제출할
> 아이디어의 **구조를 모사한 시제품**이다. 실제 모바일신분증 시스템, 정부/기관 시스템과
> **연동하지 않는다**. 기관은 전부 "○○은행(모의)"처럼 가상이고, 서명 키는 프로세스가
> 기동할 때 메모리에서 만든 모의 키이며, 보호자 알림은 발송 없이 기록만 남긴다.

## 1. 아이디어

| 지금 | 이 POC |
|---|---|
| 국민이 기관에 신분을 증명한다 | 전화를 건 기관 직원/방문자가 **재직 자격증명**으로 먼저 자신을 증명한다 |
| 국민은 상대가 진짜 직원인지 확인할 수단이 없다 | 국민은 6자리 코드를 넣고 **확인됨(초록) / 확인 불가(빨강)** 두 결과만 본다 |

역할 분담은 **"AI가 의심하고, 신분증이 확정한다"**. 이 저장소의 탐지(F-01)가 기관사칭을
의심하면 판정 응답의 `verification_prompt`로 "상대 신원을 확인하세요"라고 안내하고, 상대가
실제 직원인지는 verify-worker의 서명 검증이 확정한다. AI 판정은 확률적이라 "이 사람은 진짜
직원"이라고 확정할 수 없지만, 서명 검증은 결정적(deterministic)이다.

## 2. 구조도

```
 [모의 기관]                    [직원]                          [국민]
     │ ① 자격증명 발급               │ ② 일회용 증명 생성             │ ④ 코드 입력
     │ POST /credentials           │ POST /proofs                 │ /verify/citizen
     ▼                             ▼                              ▼
┌──────────────────── apps/verify-worker (8400, 모의) ─────────────┐  ┌──── apps/api (8000) ────┐
│ domain        Credential / Proof / VerificationResult           │  │ domain                   │
│               사유 코드(N-04), 성명 마스킹(김○○)                 │  │  decide_verification_    │
│ application   발급 / 폐기 / 증명 생성 / 검증 유스케이스           │◄─┤  prompt()  ← F-01 결과   │
│ infrastructure Ed25519 서명 어댑터(모의 키, 메모리)               │⑤ │ application              │
│               인메모리 저장소(자격증명, 폐기 목록, 증명)          │  │  CallVerificationService │
│               FastAPI, /metrics (vps_verify_*)                  │  │ infrastructure           │
└─────────────────────────────────────────────────────────────────┘  │  verify-worker 클라이언트 │
     ▲                                                               │  보호자 알림 mock         │
     │ ③ 6자리 코드를 말로 전달 (직원 → 국민)                          │  검증 기록(인메모리)      │
                                                                     └──────────────────────────┘
 ⑤ api가 /api/v1/verify 호출 → 결과를 call_id 통화 기록에 붙임 → 확인 불가면 보호자 알림(mock)
```

검증 판정 순서(`VerifyProofService`): **코드 없음 → 서명 불일치 → 폐기 → 만료 → 이미 사용됨**.
하나라도 걸리면 `verified=false`이고 사유 코드만 다르다. 서명을 먼저 보는 이유는, 위·변조된
자격증명이 "만료" 같은 가벼운 사유로 가려지지 않게 하기 위해서다. 사용 처리는 모든 검사를
통과한 뒤에만 한다(실패한 시도가 정상 증명을 소모하지 않음).

| 사유 코드 (`reason`) | 의미 | 대표 시나리오 |
|---|---|---|
| `verified` | 서명·폐기·만료·사용 여부 모두 통과 | 정상 직원 |
| `code_not_found` | 그 코드로 발급된 증명이 없음 | 사칭범 |
| `signature_invalid` | 자격증명 내용과 기관 서명이 불일치 | 위·변조 |
| `credential_revoked` | 자격증명이 폐기됨 | 퇴사자 |
| `proof_expired` | 증명 유효시간(기본 180초) 경과 | 오래된 코드 |
| `proof_already_used` | 이미 한 번 검증에 쓰인 코드 | 재사용 시도 |

**입력 실수 재시도**(api `allows_code_retry`): `code_not_found`는 사칭범일 수도, 어르신이 숫자
하나를 잘못 누른 것일 수도 있다. 그래서 같은 통화에서 **연속 첫 번째** `code_not_found`는
확인 불가로 확정하지 않고 `retry_allowed: true`로 응답한다. 이때 화면은 "숫자가 맞지 않습니다.
한 번 더 불러 달라고 하세요"를 보여주고, 보호자 알림도 남기지 않는다. 연속 두 번째부터는 확인
불가와 보호자 알림(모의)으로 처리한다. 폐기/만료/재사용/서명 불일치는 입력 실수로 생길 수 없어서
첫 시도에도 바로 확인 불가다. 연속 횟수는 다른 결과(확인됨 등)가 나오면 0부터 다시 센다.
6자리 코드를 두 번 안에 맞힐 확률은 2/10^6이라, 한 번 더 기회를 줘도 사칭범에게 실질적인
이득은 없다.

국민용 화면은 사유 코드를 보여주지 않고 두 결과만 보여준다. 사유 코드와 사람이 읽을
문구(`message`)는 API 응답과 통화 기록, 메트릭 라벨에 남는다(N-04).

**노출 최소화**: `verified=true`여도 국민에게는 기관명, 마스킹된 성명(김○○), 목적, 만료시각만
나간다. credential_id, 역할, 서명은 내보내지 않는다(`tests/test_verify_response.py`가 응답
키 집합을 고정함).

## 3. 시나리오별 요청/응답 (2026-10-12 실제 실행 결과)

`apps/verify-worker/scripts/demo_scenarios.sh`를 실행한 출력 그대로다. 코드, 시각, ID는
실행할 때마다 다르다. 국민 측 검증은 api(`POST /api/v1/calls/{call_id}/verification`,
`X-API-Key: dev-handler-key`)를 거친다.

### 시나리오 1: 정상 직원 → 확인됨

```
$ POST :8400/api/v1/proofs {"credential_id":"demo-bank-staff","purpose":"대출 상담 전화"}
{"code":"214165","purpose":"대출 상담 전화","expires_at":"2026-10-12T01:53:17.723455+00:00","ttl_seconds":180}

$ POST :8000/api/v1/calls/demo-call-1/verification {"code":"214165"}
{"call_id":"demo-call-1","verified":true,"reason":"verified",
 "message":"기관(모의)이 서명한 재직 자격증명과 일회용 증명이 모두 유효합니다.",
 "verified_at":"2026-10-12T01:50:17.757714+00:00",
 "institution_name":"○○은행(모의)","staff_display_name":"김○○","purpose":"대출 상담 전화",
 "expires_at":"2026-10-12T01:53:17.723455+00:00","guardian_notification":null}
```

### 시나리오 2: 사칭범 (발급된 적 없는 코드) → 1회차 재입력 안내, 2회차 확인 불가

입력 실수 재시도 규칙(2장)을 추가한 뒤 다시 실행한 결과다(2026-10-12). 스크립트는 연속 횟수가
이전 실행과 섞이지 않게 실행마다 다른 call_id를 쓴다.

```
$ POST :8000/api/v1/calls/demo-call-2-1791777824/verification {"code":"000000"}   # 1회차
{"call_id":"demo-call-2-1791777824","verified":false,"reason":"code_not_found",
 "message":"입력한 코드로 발급된 증명이 없습니다. 상대방이 기관 직원임을 증명하지 못했습니다.",
 "verified_at":"2026-10-12T04:03:44.891410+00:00","retry_allowed":true,"guardian_notification":null}

$ POST :8000/api/v1/calls/demo-call-2-1791777824/verification {"code":"000001"}   # 2회차
{"call_id":"demo-call-2-1791777824","verified":false,"reason":"code_not_found",
 "message":"입력한 코드로 발급된 증명이 없습니다. 상대방이 기관 직원임을 증명하지 못했습니다.",
 "verified_at":"2026-10-12T04:03:44.907613+00:00","retry_allowed":false,
 "guardian_notification":{"notification_id":"d27ee6cc-7ee2-48eb-ad18-afdef625211c","status":"logged",
   "created_at":"2026-10-12T04:03:44.907597+00:00",
   "note":"MOCK: 실제 보호자 알림(문자/푸시) 발송 없음 — 모의 시연용 기록만 남김"}}
```

시나리오 1·3의 위 응답은 재시도 규칙 추가 전 실행분이라 `retry_allowed` 필드가 없다. 지금은
두 시나리오 모두 `"retry_allowed":false`가 함께 나온다(2026-10-12 재실행으로 확인).

### 시나리오 3: 퇴사자 (증명 생성 → 폐기 → 검증) → 확인 불가

```
$ POST :8400/api/v1/credentials {"institution_name":"○○은행(모의)","staff_display_name":"최퇴사","role":"대출상담 직원"}
{"credential_id":"d63b0827-ce58-472c-aa65-6deae208adbd","institution_name":"○○은행(모의)",
 "staff_display_name":"최퇴사","role":"대출상담 직원","issued_at":"2026-10-12T01:50:17.779376+00:00",
 "signature":"275d863e…799cfc08","revoked":false}

$ POST :8400/api/v1/proofs {"credential_id":"d63b0827-…","purpose":"방문 상담"}
{"code":"407227","purpose":"방문 상담","expires_at":"2026-10-12T01:53:17.808778+00:00","ttl_seconds":180}

$ POST :8400/api/v1/credentials/d63b0827-…/revoke
{"credential_id":"d63b0827-ce58-472c-aa65-6deae208adbd","revoked":true}

$ POST :8000/api/v1/calls/demo-call-3/verification {"code":"407227"}
{"call_id":"demo-call-3","verified":false,"reason":"credential_revoked",
 "message":"자격증명이 폐기되었습니다(퇴사 등으로 더 이상 재직 중이 아님).",
 "verified_at":"2026-10-12T01:50:17.851023+00:00",
 "guardian_notification":{"notification_id":"c687d1ae-1fb1-48ba-9dbe-716395ee568a","status":"logged",…}}
```

(위 실행에서 api는 브랜치 코드를 8010 포트에 따로 띄워 호출했다. 응답 형식은 같다.)

### 판정 응답의 신원확인 안내 (`verification_prompt`)

`POST /api/v1/calls/analyze` 응답에 기존 필드는 그대로 두고 아래 필드만 추가했다.
기관사칭 패턴(`authority_impersonation`)이 있거나 `risk_level == "high"`면 안내한다.

```json
"verification_prompt": {
  "required": true,
  "message": "기관사칭 의심 표현(검찰청, 수사관)이 탐지되었습니다. 상대방에게 '확인 코드'를 불러 달라고 해서 실제 기관 직원인지 확인하세요. 확인되기 전에는 송금, 앱 설치, 개인정보 제공을 하지 마세요."
}
```

해당 없으면 `{"required": false}`다. 이 문구는 `decide_verification_prompt()`의 실제 출력
형식이다. 단, 위 키워드 예시는 단위 테스트 입력 기준이고, 실제 analyze 경로의 라이브 응답은
이번에 확인하지 못했다(아래 5장 참고).

## 4. 실측 검증 소요시간

측정 환경: Intel i7-8700(12 스레드), WSL2, Python 3.14, uvicorn 단일 워커, 같은 호스트의
루프백. 측정일 2026-10-12. warm-up 5건 후, 매번 새 증명을 만들어 `verified=true` 경로만
경로별로 200건 순차 측정했다.

| 구간 | 평균 | p50 | p95 | 최대 |
|---|---|---|---|---|
| 서버 내부: 검증 유스케이스 1건 (`vps_verify_duration_seconds` 증분 sum/count) | 0.146ms | – | – | – |
| HTTP 왕복: verify-worker `POST /api/v1/verify` 직접 | 0.96ms | 0.91ms | 1.21ms | 2.08ms |
| HTTP 왕복: api `POST /api/v1/calls/{id}/verification` 경유 | 8.73ms | 8.72ms | 9.44ms | 10.17ms |

- 서버 내부 시간은 코드 조회, Ed25519 서명 검증, 폐기/만료/사용 확인을 합친 값이다.
  히스토그램이라 p50/p95는 버킷 경계로만 알 수 있어서 평균만 적었다.
- api 경유가 약 8ms 더 걸리는 원인은 측정하지 않았다(api→verify-worker 호출마다 httpx
  연결을 새로 맺는 비용과 스레드풀 전환이 후보).
- 동시 요청, 실패 경로(`code_not_found` 등), 다른 하드웨어에서는 측정하지 않았다.

## 5. 범위와 한계

- **실제 연동 없음**: 모바일신분증, 기관 인사 시스템, 문자/푸시 발송과 연동하지 않는다.
- **키 관리**: 모의 기관 개인키를 verify-worker 메모리에 두고 검증도 같은 프로세스가 한다.
  실제 구조라면 검증 측은 기관 공개키 레지스트리만 조회해야 한다. 재시작하면 키와 기록이
  전부 사라진다.
- **인증 없음**: verify-worker의 발급/폐기/증명 생성 엔드포인트에는 RBAC를 걸지 않았다(로컬
  시연 범위). api의 검증 엔드포인트는 기존과 같이 HANDLER 키가 필요하다.
- **무차별 대입**: 6자리 코드(10^6)에 대한 속도 제한이 없다. TTL(기본 180초)과 일회용
  처리로만 완화한다.
- **검증 기록 영속화 없음**: 통화별 신원확인 기록은 api 메모리에만 있다. 감사증적 테이블
  (`call_analysis_results`)이 append-only라 UPDATE로 붙일 수 없어서, 영속화하려면 별도
  append-only 테이블을 추가해야 한다.
- **배포 미등록**: k3s/docker compose에 등록하지 않았다. Prometheus job(`poc-verify-worker`)만
  추가했고, `vps-` 생존 알림 대상에서는 의도적으로 뺐다.
- **analyze 경로 라이브 확인 못 함**: 2026-10-12 작업 시점에 docker 데몬과 postgres가 꺼져
  있어서, `/api/v1/calls/analyze`의 `verification_prompt`는 단위 테스트(4건)와 Playwright
  화면 확인(analyze 응답을 가로채서 렌더링만 확인)으로만 검증했다.
