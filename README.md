# Voice Phishing Detector (보이스피싱 실시간 탐지 및 대응 시스템)

Repo: https://github.com/pmhllll12/voice-phishing-detector

AI 데이터센터/AI 인프라 엔지니어 직무 취업을 위한 개인 포트폴리오 프로젝트.
가상 발주처(금융감독원 산하 금융사기대응센터)의 RFP를 기반으로, 제안서 → 요구사항정의서/설계서 →
구현 → 시험(검수)계획서로 이어지는 공공/금융 SI 엔드투엔드 시뮬레이션을 1인이 수행합니다.

> **현재 상태**: F-01~F-07 기능 요구사항 구현 및 로컬 검증 완료. 문서(요구사항정의서/
> 설계서/시험계획서)와 인프라(docker-compose 실제 기동, EC2 배포)는 아직 스캐폴딩
> 단계입니다. 자세한 건 아래 "진행 현황" 참고.

## 문서

- [RFP (제안요청서)](docs/RFP.md) — 사업 배경, 기능/비기능 요구사항(F-01~F-07, N-01~N-06)
- TODO: `docs/requirements.md` (요구사항정의서)
- TODO: `docs/design.md` (설계서)
- TODO: `docs/test-plan.md` (시험계획서)

## 아키텍처 개요

```
frontend (Next.js, 관제 대시보드)
   │
   ▼
api (FastAPI) ──► mcp-server (통화분석/사기패턴DB조회/신고연동 툴) ──► postgres+pgvector
   │                                                                       ▲
   └──────────────► rag-worker (유사사례 임베딩/검색) ──────────────────────┘

prometheus ──► grafana  (애플리케이션 메트릭 관측)
```

각 Python 앱(`apps/api`, `apps/mcp-server`, `apps/rag-worker`)은 헥사고날 아키텍처로
`domain/` / `application/` / `infrastructure/` 계층을 분리합니다. 상세 원칙은 [CLAUDE.md](CLAUDE.md) 참고.

## 재사용한 인프라 스킬

이전 개인 프로젝트 [gpu-fleet-ops](https://github.com/pmhllll12/gpu-fleet-ops)에서 검증한
아래 스킬을 이 프로젝트의 인프라/관측성 레이어에 그대로 적용합니다:

- Docker Compose 멀티 컨테이너 구성
- Prometheus + Grafana 모니터링 (관측 대상: GPU 메트릭 → 애플리케이션 메트릭으로 교체)
- 헥사고날 아키텍처 (domain/application/infrastructure 분리)
- AWS EC2 배포, Cloudflare Tunnel/도메인 연결
- Claude Code + MCP 서버 설정 (`.mcp.json`)
- Nginx 리버스 프록시, Full(strict) SSL

## 로컬 실행 (TODO)

```bash
# TODO: .env.example 작성 후 안내 추가
docker compose up --build
```

- api: http://localhost:8000/health
- frontend: http://localhost:3000
- prometheus: http://localhost:9090
- grafana: http://localhost:3001

## MCP 서버를 Claude Code에서 테스트하기

이 저장소 루트의 `.mcp.json`이 `voice-phishing-tools` MCP 서버를 로컬 python 프로세스로
등록해뒀습니다 (stdio transport). 먼저 의존성을 설치하세요.

```bash
cd apps/mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

(`python` 명령이 없고 `python3`만 있는 시스템이 많습니다 — 이 저장소는 `python3` 기준으로 세팅했습니다. `python -m venv ...`처럼 앞 명령이 실패하면 `&&`로 묶인 뒤 명령들도 조용히 실행되지 않으니 주의하세요.)

이후 이 저장소 루트에서 Claude Code를 실행하면 `analyze_call_pattern`,
`lookup_fraud_pattern_db`, `submit_report` 3개 툴이 자동으로 인식됩니다.
`analyze_call_pattern`(F-01/F-02)은 별도 서비스 없이 바로 동작합니다.

## mcp-server REST 어댑터 (apps/api·F-06 대시보드에 필요)

`analyze_call_pattern`과 완전히 같은 판정 로직(F-01/F-02/F-05)을 apps/api가 일반 HTTP로
호출할 수 있도록 `rest_server.py`가 별도로 떠 있어야 합니다 (server.py는 Claude Code
stdio 전용이라 apps/api가 호출할 수 없음).

```bash
cd apps/mcp-server
source .venv/bin/activate   # 위에서 이미 만든 venv 재사용
uvicorn rest_server:app --app-dir src --port 8100
```

떠 있는지 확인: `curl http://localhost:8100/health`

## rag-worker 로컬 실행 (F-04 유사사례 검색에 필요)

`lookup_fraud_pattern_db` MCP 툴은 rag-worker(F-04 유사사례 검색 API)를 HTTP로 호출합니다.
아래처럼 rag-worker를 먼저 띄워둬야 합니다 (postgres/pgvector 없이도 동작하는 v1 —
로컬 JSON 합성 데이터셋 + 문자 bigram TF-IDF 코사인 유사도로 구현됨).

```bash
cd apps/rag-worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --port 8200
```

떠 있는지 확인: `curl http://localhost:8200/health` → `{"status":"ok","corpus_size":10}`
rag-worker가 꺼져 있으면 `lookup_fraud_pattern_db`가 에러 메시지와 함께 빈 결과를 반환합니다
(mcp-server가 죽지 않고 우아하게 실패하도록 처리해뒀습니다).

## apps/api 로컬 실행 (F-03 딥보이스 판별 테스트에 필요)

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --port 8000
```

테스트 (16-bit PCM WAV 파일 업로드):
```bash
curl -X POST http://localhost:8000/api/v1/calls/deepvoice-check -F "audio=@sample.wav"
```

⚠️ v1은 실제 딥보이스 데이터로 검증되지 않은 음향 휴리스틱입니다. 판별 "정확도"가 아니라
"설명 가능한 판별 인터페이스" 자체를 보여주는 단계입니다. 자세한 한계는
`apps/api/src/infrastructure/adapters/deepvoice_adapter.py` 상단 주석 참고.

## F-06 관제 대시보드 로컬 실행

아래 3개 프로세스가 모두 떠 있어야 대시보드가 실제 데이터를 보여줍니다 (터미널 3개 필요):

```bash
# 1) mcp-server REST 어댑터 (판정 로직)
cd apps/mcp-server && source .venv/bin/activate
uvicorn rest_server:app --app-dir src --port 8100

# 2) api (오케스트레이션 + 감사증적 저장 + 통계 집계)
cd apps/api && source .venv/bin/activate
uvicorn src.main:app --port 8000

# 3) frontend
cd apps/frontend
npm install   # 최초 1회
npm run dev
```

브라우저에서 http://localhost:3000 (포트가 이미 사용 중이면 Next.js가 자동으로 3001 등으로
올립니다 — 터미널에 뜨는 실제 URL을 확인하세요). 대시보드 상단 폼에 통화 내용을 입력해
"분석하기"를 누르면 mcp-server가 판정하고, api가 그 결과를 인메모리에 적재하고,
10초마다 자동 갱신되는 통계/최근 탐지 목록에 반영됩니다.

현재 저장소는 postgres 없이 **api 프로세스 메모리**에만 기록을 쌓습니다(N-01 감사증적의
아주 단순한 v1) — api를 재시작하면 기록이 초기화됩니다. TODO: postgres로 교체.

## 데이터

실제 보이스피싱 통화 녹음 데이터는 사용하지 않습니다. 공개된 뉴스/경찰청 공개자료/시나리오
기반의 합성 데이터셋을 직접 제작해서 사용합니다. 자세한 제약사항은 [docs/RFP.md](docs/RFP.md) 4장 참고.

## 진행 현황

- [x] F-01 통화 텍스트 분석 (`apps/mcp-server`, 키워드 기반 규칙 탐지)
- [x] F-02 위험도 스코어링 (`apps/mcp-server`, 카테고리 가중치 합산 0~100점)
- [x] F-04 유사사례 매칭 (`apps/rag-worker`, 문자 bigram TF-IDF v1 + 합성 데이터셋 10건)
- [x] F-05 판정 근거 자연어 설명 (`apps/mcp-server`의 `ExplanationService`, F-01/F-02 결과를 근거로 템플릿 기반 문장 생성 — 아직 F-04와는 미결합)
- [x] F-03 딥보이스 판별 (`apps/api`, 음향 특징 휴리스틱 v1 — 피치 안정성/스펙트럼 평탄도/묵음 규칙성. **정확도 미검증, 실제 데이터로 임계값 보정 필요** — 상세: `infrastructure/adapters/deepvoice_adapter.py` 상단 주석)
- [x] F-06 관제 대시보드 (`apps/frontend`, 탐지 현황 테이블 + 위험도 분포 + 카테고리별 통계 + 통화 분석 폼. `apps/mcp-server/rest_server.py`를 새로 추가해 api가 판정 로직을 HTTP로 호출하도록 연결, api에 인메모리 감사증적 저장소 + 통계 집계 엔드포인트 추가)
- [x] F-07 신고 연동 (`apps/mcp-server`의 `submit_report` 툴 — mock. risk_level이 high면 auto, 그 외엔 manual 채널로 분류해 인메모리에 기록. **실제 112/경찰청 API 호출 없음** — RFP 데이터 제약, `ReportSubmissionService` 상단 주석 참고. 알림 발송은 아직 미구현)
- [ ] `docs/requirements.md`, `docs/design.md`, `docs/test-plan.md` 작성
- [ ] 인프라(`docker-compose.yaml`, `prometheus/prometheus.yml`, `infra/`)는 직접 손으로 채워나가기
