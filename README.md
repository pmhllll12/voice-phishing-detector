<img width="1910" height="1046" alt="Screenshot 2026-08-26 151151_edited" src="https://github.com/user-attachments/assets/dc6040c0-1a7d-47a2-8e51-df4b95ec105e" />
<img width="1900" height="1014" alt="Screenshot 2026-08-26 151128_edited" src="https://github.com/user-attachments/assets/15731636-a269-467a-9478-106b258dd16e" />
# Voice Phishing Detector (보이스피싱 실시간 탐지 및 대응 시스템)

Repo: https://github.com/pmhllll12/voice-phishing-detector

AI 데이터센터/AI 인프라 엔지니어 직무 취업을 위한 개인 포트폴리오 프로젝트.
가상 발주처(금융감독원 산하 금융사기대응센터)의 RFP를 기반으로, 제안서 → 요구사항정의서/설계서 →
구현 → 시험(검수)계획서로 이어지는 공공/금융 SI 엔드투엔드 시뮬레이션을 1인이 수행합니다.

> **현재 상태**: F-01~F-07(기능)과 N-01~N-06(비기능) 요구사항 모두 최소 1차 구현 및
> 로컬 검증 완료(2026-08-31). `docker compose up --build`로 전체 스택(frontend/api/
> mcp-server/rag-worker/stt-worker/postgres/prometheus/grafana) 실기동 확인, PR마다
> pytest 186개 자동 실행하는 CI도 구축됨. RFP → 요구사항정의서 → 설계서 → 시험계획서
> 4개 문서 전부 작성 완료. 2026-09-02: 시중 어떤 보이스피싱 차단 앱에도 없는 **크로스채널
> 상관관계 탐지**(통화→문자→이메일 다단계 공격 연계 탐지)를 신규 추가. **EC2 배포만
> 아직 TODO**입니다. 자세한 건 아래 "진행 현황" 참고.

## 문서

- [RFP (제안요청서)](docs/RFP.md) — 사업 배경, 기능/비기능 요구사항(F-01~F-07, N-01~N-06)
- [requirements.md (요구사항정의서)](docs/requirements.md) — F-01~F-07/N-01~N-06 각각의
  입력/처리/출력/수용기준(acceptance criteria)과 구현·테스트 근거
- [design.md (설계서)](docs/design.md) — 시스템 아키텍처/데이터 모델/API 명세/N-06
  확장성/배포 구조(EC2, 계획 수준) 전부 작성 완료. 배포 구조는 실배포 전이라
  인스턴스 스펙 등 세부값이 미확정으로 표시됨
- [test-plan.md (시험계획서)](docs/test-plan.md) — 테스트 전략(단위/실측데이터셋/E2E
  3계층), F-01~F-07 검수 시나리오와 실측 결과, CI 파이프라인, 알려진 커버리지 공백

## 아키텍처 개요

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
- Prometheus/Grafana 연동: rag-worker가 노출하는 `vps_rag_*` 메트릭(F-04)을 이 저장소가
  아니라 gpu-fleet-ops 저장소의 Prometheus/Grafana 스택에 별도 scrape job으로 추가해
  통합 관측 중입니다 (`gpu-fleet-ops/docker/prometheus/prometheus.yml`의 `vps-rag-worker`
  job, 대시보드는 `gpu-fleet-ops/dashboards/gpu-fleet-monitoring.json`). 별개 리포지토리지만
  같은 호스트에서 도커 브리지 네트워크로 rag-worker(호스트 프로세스)를 스크레이프합니다 —
  이때 rag-worker를 `uvicorn src.main:app --host 0.0.0.0 --port 8200`처럼 **0.0.0.0으로
  바인딩**해야 브리지 게이트웨이 IP에서 접근 가능합니다(기본값인 127.0.0.1만 바인딩하면
  Prometheus target이 `down`으로 뜹니다 — 로컬 검증 중 실제로 겪은 문제).

## 로컬 실행 (docker compose)

사전 준비: Ollama가 **호스트에서** 떠 있어야 하고(mcp-server 컨테이너가 F-01/F-02
LLM 추론에 호출함), `OLLAMA_HOST=0.0.0.0`으로 바인딩돼 있어야 합니다 — 기본값인
127.0.0.1만 바인딩하면 docker 브리지 네트워크(`host.docker.internal`)에서 접근할 수
없습니다(위 "재사용한 인프라 스킬"의 rag-worker `0.0.0.0` 바인딩 이슈와 같은 종류의
문제, 로컬 검증 중 실제로 겪음).

```bash
# 필요하면 .env.example을 .env로 복사해 포트/키를 오버라이드 (없어도 기본값으로 동작)
cp .env.example .env

docker compose up --build
```

- api: http://localhost:8000/health
- frontend: http://localhost:3000
- prometheus: http://localhost:9090
- grafana: http://localhost:3001 (기본 admin 비밀번호는 `.env.example` 참고 — 프로덕션
  에서는 반드시 교체할 것)

각 서비스는 `docker compose ps`에서 `healthy`로 뜰 때까지 순서대로 기동됩니다
(postgres → mcp-server/rag-worker/stt-worker → api → frontend). `rag-worker`는 기동
시 `scripts/seed_fraud_cases.py`로 F-04 코퍼스를 자동으로 postgres(pgvector)에
적재합니다.

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

## mcp-server gRPC 진입점 (N-06 확장성 검증용, 프로덕션 배포 대상 아님)

REST(`rest_server.py`)/MCP stdio(`server.py`)와 완전히 같은 판정 로직을 gRPC로도
제공할 수 있는지 검증하는 3번째 진입점입니다(`grpc_server.py`, 2026-09-01 추가,
`docs/design.md` N-06 확장 지점 7번 참고). `CallAnalysisService`를 그대로 재사용해
application/domain 계층 diff 0줄로 추가했고, N-02 RBAC도 grpc metadata(`x-api-key`)
로 재사용했습니다. 검증 목적이라 docker-compose에는 등록하지 않았습니다.

```bash
cd apps/mcp-server
source .venv/bin/activate
python src/grpc_server.py   # 기본 포트 8101
```

호출 예시(Python, 별도 터미널):
```python
import grpc
from infrastructure.grpc_generated import voice_phishing_pb2, voice_phishing_pb2_grpc

channel = grpc.insecure_channel("localhost:8101")
stub = voice_phishing_pb2_grpc.VoicePhishingAnalysisStub(channel)
resp = stub.Analyze(
    voice_phishing_pb2.AnalyzeRequest(transcript="검찰청 수사관인데 안전계좌로 이체하세요"),
    metadata=(("x-api-key", "dev-handler-key"),),
)
print(resp.risk_score, resp.risk_level)
```

`.proto`를 바꾸면 `protos/voice_phishing.proto` 상단 주석의 재생성 명령을 따르세요
(생성된 `_pb2_grpc.py`의 import를 상대경로로 수동 수정해야 하는 점 포함).

## rag-worker 로컬 실행 (F-04 유사사례 검색에 필요)

`lookup_fraud_pattern_db` MCP 툴은 rag-worker(F-04 유사사례 검색 API)를 HTTP로 호출합니다.
아래처럼 rag-worker를 먼저 띄워둬야 합니다 (postgres/pgvector 없이도 동작하는 v2 — 로컬 JSON
합성 데이터셋 + sentence-transformers 로컬 임베딩 모델(jhgan/ko-sroberta-multitask) + 코사인
유사도로 구현됨. GPU가 없으면 자동으로 CPU 폴백).

```bash
cd apps/rag-worker
python3 -m venv .venv && source .venv/bin/activate
# GPU(CUDA) 환경이면 requirements.txt 상단 주석대로 torch를 먼저 별도 인덱스에서 설치할 것
pip install -r requirements.txt
uvicorn src.main:app --port 8200
```

떠 있는지 확인: `curl http://localhost:8200/health` →
`{"status":"ok","corpus_size":10,"embedding_model":"jhgan/ko-sroberta-multitask","device":"cuda"}`
(GPU가 없으면 `device`가 `cpu`로 표시됩니다)
rag-worker가 꺼져 있으면 `lookup_fraud_pattern_db`가 에러 메시지와 함께 빈 결과를 반환합니다
(mcp-server가 죽지 않고 우아하게 실패하도록 처리해뒀습니다). v1(TF-IDF)은
`RAG_DEBUG_COMPARE=1` 환경변수로 켜면 비교 로그용으로 계속 쓰입니다(위 "진행 현황" 참고).

## stt-worker 로컬 실행 (모바일 실시간 감지 파이프라인용, 진행 중)

F-01은 지금까지 통화 텍스트를 직접 입력받는 걸 전제로 했습니다. `apps/stt-worker`는 모바일
앱이 5~10초 단위로 잘라 보내는 오디오 청크를 faster-whisper(CTranslate2 기반 로컬 Whisper)로
텍스트 변환하는 별도 서비스입니다 — 변환된 텍스트를 api가 이어서 mcp-server(F-01/F-02)에
넘기는 구조입니다. 아직 docker-compose.yaml/api 연동 전 단계(뼈대만 완성, 진행 현황 참고).

```bash
cd apps/stt-worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# GPU(CUDA)에서 쓰려면 cuBLAS/cuDNN 라이브러리 경로를 명시해야 합니다 — 위 pip install로
# nvidia-cublas-cu12/nvidia-cudnn-cu12는 받아지지만, ctranslate2가 시스템 라이브러리
# 경로에서 자동으로 찾지 못합니다(requirements.txt 상단 주석 참고).
export LD_LIBRARY_PATH="$(python -c 'import os,nvidia.cublas,nvidia.cudnn as c;print(os.path.dirname(nvidia.cublas.__file__)+"/lib:"+os.path.dirname(c.__file__)+"/lib")')"
uvicorn src.main:app --port 8300
```

떠 있는지 확인: `curl http://localhost:8300/health` → `{"status":"ok","model":"small","device":"cuda","compute_type":"int8_float16"}`
(cuBLAS/cuDNN 경로를 못 찾거나 GPU가 없으면 `device`가 `cpu`로 표시됩니다 — 생성자 통과 후
무음 버퍼로 실제 추론까지 태워보고 나서 폴백 여부를 정확히 판단합니다,
`infrastructure/adapters/faster_whisper_adapter.py`의 `_load_and_warm_up()` 참고).

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
"분석하기"를 누르면 mcp-server가 판정하고, api가 그 결과를 postgres 감사증적에 적재하고,
10초마다 자동 갱신되는 통계/최근 탐지 목록에 반영됩니다.

N-01 감사증적(api의 통화 판정 로그, mcp-server의 신고 접수 기록)은 postgres에 저장됩니다
(`infra/db/init.sql`) — api를 재시작해도 기록이 남습니다. UPDATE/DELETE는 DB 트리거로
아예 거부되어 애플리케이션 코드와 무관하게 append-only가 보장됩니다(`infra/db/init.sql`의
`reject_audit_log_mutation`). 로컬 postgres는 systemd가 아니라 별도 docker 컨테이너로
띄웁니다 — 기동 방법은 `run-voice-phishing-detector` 스킬의 Prerequisites 참고.

## Health Check (`/health` vs `/ready`)

4개 백엔드 서비스(api/mcp-server/rag-worker/stt-worker) 모두 `/health`와 `/ready`를
둘 다 제공합니다. 역할이 다릅니다:

- **`/health`**: "프로세스가 살아있는가"만 본다. 항상 `{"status": "ok"}` 계열 응답,
  항상 200. 이 프로세스 안에서 완결되는 정보만 보여준다(모델 로드 시점의
  device/compute_type 등).
- **`/ready`**: "지금 실제로 요청을 처리할 수 있는가"를 실제 의존 서비스 호출/자가
  점검으로 확인한다. 응답 형식은 `{"status": "ok"|"degraded"|"error", "checks": {...}}`.

실제로 배선된 의존관계만 확인합니다 — rag-worker는 아직 REST 경로에서 analyze_call_pattern에
결합될 때만 간접적으로 쓰이고(F-04, 실패해도 그냥 유사사례 없이 진행) 별도 헬스체크
대상은 아닙니다. 각 서비스가 실제로 호출하는 대상만 체크 대상에 넣습니다(체크해봤자 실제
의존관계를 반영 못 하는 거짓 정보는 만들지 않는다는 원칙).

| 서비스 | `/ready`가 확인하는 것 | 실패 시 |
|---|---|---|
| api | mcp-server `/health`(얕은 호출, 순환 방지) — 다운되면 F-01/F-02/F-05 전체 불가 | `status="error"`, HTTP 503 |
| api | postgres(N-01 감사증적) — analyze_call이 매번 여기 쓰기 때문에 mcp-server와 동급 | `status="error"`, HTTP 503 |
| api | stt-worker `/health` — F-05 오디오 업로드 경로에만 필요, 텍스트 경로는 무관 | `status="degraded"`, **HTTP 200** |
| mcp-server | Ollama `/api/version` (`CALL_ANALYSIS_BACKEND=rule`이면 `not_applicable`) | `status="degraded"`, **HTTP 200** — 규칙 기반(v1) 자동 폴백이 있어 서비스 자체는 계속 요청을 처리할 수 있으므로 503이 아니다 |
| mcp-server | postgres(N-01, F-07 신고 접수 기록) — `/api/v1/analyze`는 이것 없이도 동작 | `status="degraded"`, **HTTP 200** |
| rag-worker | 자기 자신의 검색 서비스로 실제 검색 1건 self-test | `status="error"`, HTTP 503 |
| stt-worker | 자기 자신의 STT 서비스로 무음 0.5초 오디오 실제 transcribe self-test | `status="error"`, HTTP 503 |

`/health`는 기존 그대로이므로 `run-voice-phishing-detector` 스킬의 기동 확인 폴링,
프런트엔드 에러 처리 등 기존 동작에 영향이 없습니다.

## postgres 단일 장애점 완화

api/mcp-server/rag-worker가 전부 postgres 하나에 의존하는 단일 장애점이라
2026-09-01에 3가지를 실측 적용했습니다. 상세 근거는 [design.md 6장](docs/design.md)
참고.

1. **`restart: unless-stopped`** — `docker-compose.yaml` 전 서비스에 적용. 단,
   `docker stop`/`docker kill`처럼 의도된 중지는 이 정책이 되돌리지 않습니다(Docker
   표준 동작, 실측 확인).
2. **애플리케이션단 재연결** — postgres가 재기동돼도 커넥션 객체가 끊긴 채로 남아
   `/ready`가 계속 실패하는 걸 실제로 재현했습니다. `PostgresCallLogRepository`/
   `PostgresReportRepository`/`PgvectorSimilarityAdapter` 3곳에 재연결 로직을
   추가하고, api를 재시작하지 않은 채 postgres만 재기동시켜 자동 복구되는 것까지
   라이브로 확인했습니다.
3. **백업/복구** — `infra/db/backup_postgres.sh`(pg_dump + gzip)로 정기 백업하고,
   복구는 아래처럼 합니다(스크래치 컨테이너로 왕복 검증 완료):
   ```bash
   ./infra/db/backup_postgres.sh   # backups/vps_detector_<timestamp>.sql.gz 생성
   # 복구:
   gunzip -c backups/vps_detector_<timestamp>.sql.gz | \
     PGPASSWORD=vps_dev_password psql -h localhost -U vps_app -d vps_detector
   ```
   정기 실행은 배포 환경에 맞는 스케줄러로 등록하세요(예: cron
   `0 3 * * * cd /path/to/repo && ./infra/db/backup_postgres.sh`).

복제(replica)/자동 페일오버는 도입하지 않았습니다 — 단일 인스턴스 규모에서 비용/
복잡도 대비 실익이 적다고 판단했습니다(design.md 6장 "아직 안 한 것" 참고).

## GPU 자원 사용

RTX 3050(8GB VRAM) 한 장에서 임베딩 모델(rag-worker)과 LLM(mcp-server가 호출하는 Ollama)을
**동시에** 서빙합니다. 아래 수치는 실측치입니다(각 프로세스의 `/metrics`에서 확인, 하단
"Prometheus 메트릭" 참고):

- 임베딩 모델(jhgan/ko-sroberta-multitask, rag-worker 프로세스 내 torch): 약 431MB
  (`vps_rag_gpu_memory_allocated_bytes`)
- LLM(EXAONE 3.5 2.4B Q4_K_M, Ollama 프로세스): 약 1.87GB (`vps_mcp_llm_gpu_memory_bytes`,
  Ollama `GET /api/ps`의 `size_vram` 기준)
- 둘을 합쳐도 약 2.3GB — 시스템/디스플레이(Xwayland 등) 오버헤드를 더해도 여유 VRAM
  약 4GB 확보. 7B급 모델 대신 2~3B급(EXAONE 3.5)을 고른 이유이기도 합니다(자세한 배경은
  `apps/mcp-server/src/infrastructure/adapters/ollama_call_analysis_adapter.py` 상단 주석).

⚠️ Ollama는 일정 시간 유휴 상태면 모델을 GPU에서 자동 언로드합니다. 언로드된 상태에서의
첫 요청은 콜드 스타트 로딩 때문에 수 초~10초 이상 걸릴 수 있습니다 — 로컬 테스트 중
api→mcp-server 기본 타임아웃(10초)에 실제로 걸려 실패하는 걸 재현/확인해서, 타임아웃을
30초로 늘려뒀습니다(`apps/api/src/infrastructure/adapters/mcp_client_adapter.py`).

## Prometheus 메트릭

api/rag-worker/mcp-server/stt-worker 4개 서비스 전부 `/metrics`에서 `vps_` 접두사
커스텀 메트릭을 노출합니다.

**api (`vps_*`, F-01~F-03/F-07/N-05)**
- `vps_calls_analyzed_total{risk_level}` — 처리된 통화/문자 건수(저/중/고)
- `vps_risk_score_distribution` — 위험도 스코어 분포(0~100)
- `vps_deepvoice_detected_total{result}` — F-03 딥보이스 판별 결과(synthetic/authentic)
- `vps_analysis_duration_seconds` — N-05 판정 소요시간(5초 이내 SLA 계측용)
- `vps_reports_submitted_total{channel}` — F-07 신고 접수 건수(자동/수동)
- `vps_deepvoice_inference_duration_seconds` — F-03 v2(wav2vec2) 모델 추론 1건 소요 시간
- `vps_deepvoice_model_load_duration_seconds` — F-03 v2 모델 콜드스타트 로딩 시간(1회성)
- `vps_deepvoice_model{model_name,device}` — 현재 떠 있는 F-03 v2 모델/디바이스 구성

**rag-worker (`vps_rag_*`, F-04)**
- `vps_rag_embedding_inference_duration_seconds` — 쿼리 1건을 임베딩 벡터로 인코딩하는 데
  걸린 시간
- `vps_rag_embedding_search_requests_total{result}` — 유사사례 검색 요청 수(success/error)
- `vps_rag_gpu_memory_allocated_bytes` — 이 프로세스가 점유 중인 GPU 메모리(CPU 폴백 시 0)
- `vps_rag_model_load_duration_seconds` — 서버 시작 시 임베딩 모델 로딩 시간(1회성)
- `vps_rag_embedding_model_info{model_name,device}` — 현재 모델/디바이스 구성

**mcp-server (`vps_mcp_*`, F-01/F-02)**
- `vps_mcp_llm_inference_duration_seconds` — LLM 호출 1건(콜드 스타트 로딩 포함) 소요 시간
- `vps_mcp_llm_analysis_requests_total{result}` — 통화 분석 요청 수(success/fallback) —
  fallback이 계속 늘면 Ollama 쪽에 문제가 있다는 신호로 알림에 쓸 수 있음
- `vps_mcp_llm_gpu_memory_bytes` — Ollama가 보고하는, 로드된 모델의 GPU 메모리(언로드 시 0)
- `vps_mcp_llm_model_load_duration_seconds` — 콜드 스타트 로딩 시간(캐시 히트 시 0에 가까움)
- `vps_mcp_llm_model_info{model_name,base_url}` — 현재 모델/엔드포인트 구성

이 저장소 자체의 `prometheus/prometheus.yml`은 4개 서비스(api/mcp-server/rag-worker/
stt-worker) 전부에 대한 scrape 대상이 설정돼 있고, `docker compose up`으로 뜨는 이
저장소의 prometheus(포트 9090)가 실제로 수집합니다. 다만 grafana(포트 3001)에는 아직
대시보드 패널이 연결돼 있지 않습니다(`grafana/provisioning`은 뼈대만 있음) — 이
저장소와 별개로, 통합 관측 용도로는 gpu-fleet-ops의 Prometheus/Grafana도 같이 쓰고
있습니다(위 "재사용한 인프라 스킬" 참고).

## 데이터
<img width="1900" height="1014" alt="Screenshot 2026-08-26 151128_edited" src="https://github.com/user-attachments/assets/606a74fc-6a51-44db-8f45-c57688b047e2" />

실제 보이스피싱 통화 녹음 데이터는 사용하지 않습니다. 공개된 뉴스/경찰청 공개자료/시나리오
기반의 합성 데이터셋을 직접 제작해서 사용합니다. 자세한 제약사항은 [docs/RFP.md](docs/RFP.md) 4장 참고.

## 진행 현황

- [x] F-01 통화 텍스트 분석 (`apps/mcp-server`, 키워드 기반 규칙 탐지(v1)에서 로컬 LLM
      (Ollama, EXAONE 3.5 2.4B Q4_K_M) 기반 판정으로 교체 — Ollama의 JSON Schema 강제
      출력(grammar-constrained decoding)으로 파싱 실패 없이 구조화된 결과만 받도록 하고,
      Ollama 미기동/타임아웃/파싱 오류 시 키워드 규칙 기반(v1)으로 자동 폴백)
- [x] F-02 위험도 스코어링 (`apps/mcp-server`, 카테고리 가중치 합산 대신 F-01과 같은 LLM
      호출에서 0~100 위험도 점수를 함께 산출 — 별도 스코어링 로직 없이 동일 어댑터 공유)
- [x] F-04 유사사례 매칭 (`apps/rag-worker`, 문자 bigram TF-IDF v1에서 sentence-transformers
      로컬 임베딩 모델(jhgan/ko-sroberta-multitask) + 코사인 유사도로 교체, 합성 데이터셋
      10건. `RAG_DEBUG_COMPARE=1`로 TF-IDF와 나란히 돌려 실측 비교함 — 예: "검찰 사칭"
      시나리오를 원문과 다른 표현으로 바꾼 질의에서 TF-IDF는 무관한 택배사칭형(FC-006,
      유사도 0.074)을 2위로 골랐지만 임베딩은 실제로 관련 있는 검찰 출석요구형(FC-008,
      유사도 0.701)을 2위로 정확히 찾음. 코퍼스가 10건뿐이라 이 사례가 전반적 성능을
      대표하지는 않으며, 어디까지나 실측 1건 확인 수준)
- [x] F-05 판정 근거 자연어 설명 (`apps/mcp-server`의 `ExplanationService`, F-01/F-02 결과를 근거로 템플릿 기반 문장 생성 — 아직 F-04와는 미결합)
- [x] F-03 딥보이스 판별 (`apps/api` — v1 음향 특징 휴리스틱에서, 검증된 오픈소스
      스푸핑 탐지 모델(wav2vec2 기반, HuggingFace Hub)로 교체 완료. v1은 폐기하지 않고
      모델 로드/추론 실패 시 자동 폴백 + N-04 보조 지표로 계속 사용 — 상세는 아래
      "N-05/F-03 v2" 항목과 `infrastructure/adapters/wav2vec2_deepvoice_adapter.py`
      상단 주석 참고)
- [x] F-06 관제 대시보드 (`apps/frontend`, 탐지 현황 테이블 + 위험도 분포 + 카테고리별 통계 + 통화 분석 폼. `apps/mcp-server/rest_server.py`를 새로 추가해 api가 판정 로직을 HTTP로 호출하도록 연결, api에 인메모리 감사증적 저장소 + 통계 집계 엔드포인트 추가)
- [x] F-07 신고 연동 (`apps/mcp-server`의 `submit_report` 툴 — mock. risk_level이 high면 auto, 그 외엔 manual 채널로 분류해 인메모리에 기록. **실제 112/경찰청 API 호출 없음** — RFP 데이터 제약, `ReportSubmissionService` 상단 주석 참고. 알림 발송은 아직 미구현)
- [ ] `docs/requirements.md`, `docs/test-plan.md` 작성, `docs/design.md` 나머지 챕터
      (지금은 N-06만 완성 — [Jekyll 제안서 사이트](jekyll/)가 RFP/구현 이력을 9챕터+
      부록 4개로 정리해뒀지만, 정식 요구사항정의서/시험계획서는 별도로 아직 없음)
- [x] 모바일 실시간 감지 파이프라인용 STT (`apps/stt-worker`, faster-whisper 기반
      오디오→텍스트 변환) — 헥사고날 구조/Prometheus 메트릭(`vps_stt_*`) 완성,
      `apps/api` 연동 완료, `docker-compose.yaml`에도 등록 완료(아래 참고)
- [x] Health Check 고도화 (`/health`는 그대로 두고 4개 백엔드 서비스 모두에 `/ready` 신규
      추가 — 실제 의존 서비스(mcp-server→Ollama) 호출/자가 점검 기반, 위 "Health Check"
      절 참고. 단위 테스트 9건 추가, 실제 서비스 재시작 후 정상/장애 양쪽 경로 curl로 검증)
- [x] 모바일 실시간 감지 파이프라인용 STT를 apps/api에 연결 (오디오 업로드 →
      stt-worker `/api/v1/transcribe` → 기존 텍스트 판정 경로 재사용. `/ready`에
      stt-worker 체크도 추가, 다운돼도 degraded로만 표시)
- [x] F-07 신고 연동을 REST/대시보드까지 연결 (mcp-server `submit_report`가 MCP 툴로만
      있던 것을 `POST /api/v1/reports`로 노출, api에도 동일 엔드포인트 추가. 프런트
      대시보드의 고위험 판정 행에 "신고 접수" 버튼 노출)
- [x] F-04 유사사례를 F-05 판정 근거에 결합 (위험 정황이 감지되면 rag-worker 검색 결과를
      근거 문장에 자동 인용 — rag-worker가 죽어도 analyze_call_pattern 자체는 계속
      동작하도록 예외를 삼키고 빈 결과로 폴백)
- [x] F-01/F-02 합성 통화 시나리오 데이터셋 26건으로 가중치/임계값 검증 (`apps/mcp-server/
      data/synthetic_call_transcripts.json`) — 정상 통화 오탐 없음, 카테고리 조합별
      위험도 등급이 설계 의도대로 나옴을 확인해 가중치/임계값은 그대로 유지. 키워드가
      못 잡는 자연어 표현 사각지대도 문서화(LLM 백엔드가 대부분 커버)
- [x] N-01 감사증적을 postgres로 전환 (`infra/db/init.sql` — api의 통화 판정 로그,
      mcp-server의 신고 접수 기록. UPDATE/DELETE를 DB 트리거로 거부해 append-only를
      애플리케이션 코드가 아니라 DB 레벨에서 강제. 로컬은 systemd가 아니라 docker
      컨테이너로 실행 — `run-voice-phishing-detector` 스킬 Prerequisites 참고. F-04
      rag-worker의 pgvector 이전은 범위 밖으로 남겨둠)
- [x] F-04 유사사례 검색을 postgres+pgvector로 전환 (`infra/db/init.sql`의 `fraud_cases`
      테이블 — 임베딩(sentence-transformers, 768차원)을 프로세스 메모리가 아니라
      postgres에 저장/검색. `<=>` 코사인 거리 연산자로 postgres가 직접 정렬. 코퍼스는
      `scripts/seed_fraud_cases.py`로 시드, `fraud_cases.json`은 소스 오브 트루스로 유지)
- [x] N-02 접근통제(RBAC) — 조회(VIEWER)/처리(HANDLER)/관리자(ADMIN) 3단계 계층 구조를
      `X-API-Key` 헤더 기반으로 apps/api에 도입 (`infrastructure/adapters/
      api_key_role_auth.py`). health/ready/metrics는 인프라 컴포넌트 전용이라 미인증.
      mcp-server(8100 직접 노출)에는 아직 미적용 — 알려진 범위 밖
- [x] F-03 딥보이스 임계값을 실측 데이터셋으로 보정 (`apps/api/data/deepvoice_samples/`
      — 공개 TTS(gTTS) 합성 음성 8건 + 라이선스가 명확한 실제 인간 발화(LibriSpeech,
      CC BY 4.0) 8건. 기존 임계값이 재현율 0%였음을 실측으로 확인 후 재보정해 재현율
      7/8, 오탐 2/8로 개선. 자연 발화 표본이 얇은 지표(묵음 규칙성)는 근거 없이
      건드리지 않고 한계를 코드 주석에 명시)
- [x] N-03 개인정보 마스킹 (`apps/api/src/domain/pii_masking.py` — 전화번호/계좌번호/
      주민등록번호/이름+호칭 정규식 기반 v1. mcp-server에는 마스킹된 텍스트만 전달하고,
      N-02 RBAC과 결합해 원문(raw_transcript)은 ADMIN 권한 응답에만 노출)
- [x] N-06 확장성 설계 문서화 ([`docs/design.md`](docs/design.md) — 포트-어댑터 패턴으로
      판정 알고리즘/검색 알고리즘/감사증적 저장소를 3번 실제로 교체한 이력을 근거로
      "재설계 없는 확장"을 검증. 새 사기유형 추가 절차도 구체적으로 문서화)
- [x] N-02 RBAC을 mcp-server REST 어댑터까지 확장 (docker-compose가 8100 포트를 직접
      노출해 apps/api를 우회할 수 있던 경로를 막음 — apps/api와 동일한 Role 계층을
      mcp-server에도 도입, apps/api는 서비스 자격증명(`MCP_SERVICE_API_KEY`)으로 통과.
      MCP stdio 진입점은 로컬 신뢰 실행 경로라 대상에서 의도적으로 제외)
- [x] N-05 응답시간 계측 (`vps_analysis_duration_seconds`/`vps_calls_analyzed_total`/
      `vps_risk_score_distribution`/`vps_deepvoice_detected_total`을 apps/api 판정
      엔드포인트에 실제로 연결 — `/metrics`에 노출되는 것까지 확인. "5초 이내" SLA
      자체는 계측 배선만 완료된 상태이고, 실트래픽 기준 검증은 아직 TODO)
- [x] F-03 딥보이스 판별을 검증된 오픈소스 모델(v2)로 교체 — HuggingFace Hub의 공개
      스푸핑 탐지 모델 두 개를 F-03 실측 데이터셋(16건)에 직접 태워 비교(재현율
      3/8 vs 8/8)한 뒤 `mo-thecreator/Deepfake-audio-detection`(wav2vec2-base) 채택.
      `DeepvoiceDetectionPort` 인터페이스는 그대로 유지해 N-06 확장성의 4번째 실증
      축이 됨(application 계층 diff 0줄). v1은 폴백 겸 N-04 보조 지표로 계속 사용
- [x] 프론트엔드에 F-05 오디오 입력 추가 (`AnalyzeCallForm`에 마이크 녹음 버튼 —
      브라우저 `MediaRecorder`로 녹음 → `apps/api`의 `/api/v1/calls/analyze-audio`로
      업로드. 기존 텍스트 입력 경로는 그대로 유지. 마이크 권한/장치 에러를 원인별로
      구분해 안내하도록 처리)
- [x] `docker-compose.yaml` 실기동 확인 — 전체 스택(frontend/api/mcp-server/rag-worker/
      stt-worker/postgres/prometheus/grafana)이 `docker compose up --build`로 실제로
      뜨는 것까지 검증(각 서비스 healthcheck 통과). 이 과정에서 stt-worker가
      compose에 아예 등록 안 돼 있던 것, rag-worker Dockerfile이 `scripts/`를 이미지에
      안 담아서 F-04 코퍼스 시딩이 실패하던 것, 쓰이지 않는 redis 서비스가 남아있던
      것, grafana 비밀번호가 문자 그대로 `"TODO"`였던 것을 실제로 발견해 고쳤다.
      환경변수는 `${VAR:-기본값}` 패턴으로 빼서 `.env.example`로 문서화함.
      **EC2 배포는 아직 TODO** — 다음 단계로 별도 진행 예정
- [x] F-03 v2에 서빙 관측 메트릭 추가 (`vps_deepvoice_inference_duration_seconds`/
      `vps_deepvoice_model_load_duration_seconds`/`vps_deepvoice_model` — rag-worker/
      stt-worker가 이미 갖고 있던 "추론시간/콜드스타트/모델정보" 3종 패턴을 F-03에도
      맞춤. 실측: 콜드스타트 로딩 2.47초, 추론 1건 0.54초(CPU). 전용 추론 서버
      (Triton 등)는 지금 규모(94.6M 파라미터, 로컬 요청 시 호출)에서는 불필요하다고
      판단해 도입하지 않음 — 판단 근거와 재검토 조건은
      `wav2vec2_deepvoice_adapter.py` 상단 "WHY 전용 추론 서버가 아직 없는가" 참고)
- [x] GitHub Actions CI 구축 (`.github/workflows/tests.yml` — push/PR마다 4개
      서비스 pytest 154개를 병렬 job으로 자동 실행. postgres 의존 테스트는
      skipif로 건너뛰지 않고 서비스 컨테이너로 실제로 돌림. Ollama 없이도
      mcp-server 71개가 전부 통과하는 걸 로컬에서 Ollama를 직접 내려서 확인한
      뒤 워크플로우를 작성함. 2026-08-31 기준 push/PR 양쪽에서 8개 job 전부 통과)
- [x] `docs/requirements.md`(요구사항정의서) 작성 — F-01~F-07/N-01~N-06 각각의
      입력/처리/출력/수용기준과 구현·테스트 근거, 요구사항 추적표(traceability matrix)
- [x] `docs/design.md` 나머지 챕터 작성 — 시스템 아키텍처/데이터 모델/API 명세
      (N-06 확장성 챕터는 기존 유지)
- [x] `docs/test-plan.md`(시험계획서) 작성 — 테스트 전략 3계층, 서비스별 테스트
      구성표, F-01~F-07 검수 시나리오와 실측 결과(RBAC 매트릭스 포함), CI 파이프라인,
      알려진 커버리지 공백(N-05 실트래픽 미검증 등)을 정직하게 명시
- [x] `docs/design.md` 4장 배포 구조를 계획 수준으로 작성 (Cloudflare Tunnel로
      인바운드 포트 전면 차단하는 이유, 7개 서비스 중 frontend/api 2개만 공개하는
      공개범위 표, Nginx+Cloudflare Origin CA로 Full(strict) TLS 구성, GPU vs CPU
      인스턴스 트레이드오프, 배포 절차 7단계 — 실제 EC2 배포 전이라 인스턴스 스펙
      등은 "미확정"으로 정직하게 표시). **실제 EC2 배포 자체는 여전히 TODO**
- [x] N-05 응답시간 SLA 실트래픽 검증 (2026-09-01) — 합성 데이터셋 26건으로
      실제 `/api/v1/calls/analyze`에 부하를 걸어 측정. 순차 요청(동시성 1)은
      평균 2.11초/p95 2.81초로 SLA(5초) 충족, **동시 요청 4건에서는 평균
      8.75초/p95 18.86초로 94.9%가 SLA 위반** — GPU 1장(RTX 3050)을
      Ollama/wav2vec2/임베딩/STT가 나눠 쓰는 구조적 한계. gpu-fleet-ops
      Prometheus에 `vps-api` 스크레이프 job 추가 + Grafana에 p95/p99 패널
      추가(`gpu-fleet-ops/dashboards/gpu-fleet-monitoring.json`)로 실측/교차검증.
      해결 시도는 아래 항목 참고
- [x] N-03 이름 마스킹 정량 평가 (2026-09-01) — 라벨 28건(`apps/api/data/
      pii_masking_eval.json`)으로 측정: 보정 전 정밀도 0.615/재현율 0.727,
      **"고객님/이용자님/신청자님/조사관님" 같은 흔한 단어가 성씨로 시작해
      이름으로 오탐**되는 게 정밀도를 크게 깎았음을 확인. 실측된 오탐 단어
      10개를 블록리스트로 제외해 정밀도 1.0으로 개선(재현율은 0.727 그대로 —
      블록리스트는 정밀도만 개선). 남은 재현율 공백(성씨 목록 밖/호칭 분리/
      반말)은 정규식 기반의 근본 한계로 문서화, `test_pii_masking_eval.py`로
      회귀 가드
- [x] postgres 단일 장애점 완화 (2026-09-01) — docker-compose 전 서비스에
      `restart: unless-stopped` 적용(단, 의도된 `docker stop`/`kill`은 안
      살아남을 실측 확인). **더 중요한 발견**: postgres가 재기동돼도
      api/mcp-server/rag-worker의 커넥션 객체는 끊긴 채로 남아 `/ready`가
      계속 실패하는 걸 재현 — 3곳(`PostgresCallLogRepository`/
      `PostgresReportRepository`/`PgvectorSimilarityAdapter`)에 재연결 로직
      추가하고, api 재시작 없이 postgres만 재기동시켜 자동 복구되는 것까지
      라이브로 검증. `infra/db/backup_postgres.sh`(pg_dump)로 백업/복구
      왕복도 실측(스크래치 컨테이너에 복구해 10건 정확히 돌아옴 확인).
      복제/자동 페일오버는 비용 대비 실익이 적다고 판단해 미도입
      (`docs/design.md` 6장 참고)
- [x] N-05 동시성 SLA 해결 시도 (2026-09-01) — mcp-server/rag-worker의 REST
      핸들러가 동기 블로킹 호출(Ollama/GPU 임베딩)을 직접 불러 이벤트
      루프를 막던 버그를 발견(우발적으로 요청이 한 번에 하나씩만 처리됨).
      `run_in_threadpool` + `asyncio.Semaphore`(`LLM_MAX_CONCURRENCY`)로
      수정해 재측정: 꼬리 지연시간(p95/p99/최대)은 30~40% 개선(최대
      22.1초→11~14초대)했지만, **평균 지연시간(8.1~8.3초)과 SLA 위반
      비율(96~99%)은 거의 그대로** — 세마포어 값(1/2/4)도 결과에 거의
      영향 없었음. 이걸로 병목이 소프트웨어가 아니라 GPU 용량 자체임을
      확정. GPU 증설/수요측 속도제한은 아직 미도입 — `test_llm_concurrency_
      limit.py`로 제한 메커니즘 자체는 회귀 가드
- [x] F-03 v2 일반화 검증 (2026-09-01) — 보정 데이터셋(16건, gTTS 전용/자연발화
      전부 영어)과 별도인 홀드아웃 48건(`data/deepvoice_generalization_samples/`)
      으로 검증: TTS 엔진 2종(gTTS/edge-tts) × 자연 발화 언어 2종(영어
      LibriSpeech/한국어 Zeroth-Korean, CC BY 4.0)으로 "같은 엔진만 봤다"/
      "언어를 구분한 것 아니냐"는 두 교란 요인을 통제. **결과: 전체 47/48
      (97.9%), 처음 보는 엔진(edge-tts)과 한국어 실제 발화 양쪽 다 12/12
      완벽 분리** — 일반화 우려를 실측으로 크게 줄임. `test_deepvoice_
      generalization.py`로 회귀 가드
- [x] mcp-server 신규 진입점(gRPC) 확장 검증 (2026-09-01) — N-06 "새 진입점
      프로토콜 추가"가 아직 검증 안 된 확장 축이었던 걸 실제로 해소. REST/MCP
      stdio 2개 진입점과 완전히 같은 `CallAnalysisService`를 gRPC로도 감싸서
      (`grpc_server.py`) application/domain 계층 diff 0줄로 3번째 진입점을
      추가했고, N-02 RBAC(`Role`/`API_KEYS`)도 grpc metadata로 재사용해
      인증/인가까지 실제 gRPC 클라이언트로 검증(`test_grpc_server.py` — 정상
      호출/미인증/권한부족 3가지). 검증 목적이라 docker-compose 등록은 안 함
- [x] 크로스채널 상관관계 탐지 (2026-09-02) — 시중 보이스피싱 차단 앱(에이닷 전화,
      시티즌코난, 후후 등)은 전부 자기 채널 안에서만 판단하지만, 실제 공격은 "전화로
      신뢰 형성 → 문자로 악성 링크 → 이메일로 위장 공문" 같은 다단계 공격으로 진화하고
      있다는 게 이 기능의 문제의식이다. 새 MCP 툴 `correlate_multichannel_signals`
      (`apps/mcp-server`)가 전화번호/계좌번호/URL을 정규식으로 추출해 채널(통화/문자/
      이메일)별 시각과 함께 기록하고, 다른 채널에서 같은 값이 시간 윈도우(기본 30분)
      안에 발견되면 위험도에 가산점(건당 15점, 상한 30점)을 주고 F-05 판정 근거에
      "N분 전 문자 채널에서 동일 계좌번호가 감지되었습니다" 식 문장을 추가한다.
      `analyze_call_pattern`이 call 채널 신호를 자동으로 기록/조회하도록 결합했고,
      실제 REST 호출(`/api/v1/analyze`, `/api/v1/correlate`)로 검찰 사칭 통화(65점)가
      12분 전 문자와 같은 계좌번호를 공유해 80점(HIGH)으로 오르는 것까지 실측 확인함.
      원래 작업지시서는 "ERD의 AUDIT_LOGS가 entity_type/entity_id로 범용 참조하게
      설계돼 있어 새 테이블이 불필요하다"고 가정했지만, 재검증 결과 그런 파일/컬럼이
      실제로는 없어서 전용 테이블(`channel_signals`, `infra/db/init.sql`)을 새로
      추가했다 — 이 정정도 N-06 확장성 검증의 일부로 문서화함(`docs/design.md` 참고).
      엔티티 값은 항상 마스킹해서 노출한다(N-03과 같은 원칙). **알려진 한계**: apps/api는
      mcp-server 호출 전에 통화 텍스트를 마스킹하므로(N-03), REST 경로에서는 전화번호/
      계좌번호 상관관계가 실질적으로 매칭되지 않고 URL만 자동 작동한다 — 마스킹 전
      원문에서 엔티티만 추출해 mcp-server로 넘기는 apps/api 측 별도 경로가 필요한데,
      범위가 커서 이번 이터레이션에는 포함하지 않았다(다음 과제). sms/email 채널 자체의
      실채널 연동(SMS 수신, Gmail API 등)도 범위 밖 — 합성 시나리오 데이터셋
      (`apps/mcp-server/data/synthetic_multichannel_signals.json`, 4개 시나리오)으로
      상관관계 로직만 검증했다. Google Safe Browsing 연동(선택 항목)은 미포함.
<img width="1900" height="1014" alt="Screenshot 2026-08-26 151128_edited" src="https://github.com/user-attachments/assets/5bf57efc-0385-4623-8cec-82461d236ffd" />
<img width="1910" height="1046" alt="Screenshot 2026-08-26 151151_edited" src="https://github.com/user-attachments/assets/4b36260b-be9d-400e-bbbb-15154a82a299" />
