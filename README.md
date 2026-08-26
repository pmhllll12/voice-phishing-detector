<img width="1910" height="1046" alt="Screenshot 2026-08-26 151151_edited" src="https://github.com/user-attachments/assets/dc6040c0-1a7d-47a2-8e51-df4b95ec105e" />
<img width="1900" height="1014" alt="Screenshot 2026-08-26 151128_edited" src="https://github.com/user-attachments/assets/15731636-a269-467a-9478-106b258dd16e" />
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
"분석하기"를 누르면 mcp-server가 판정하고, api가 그 결과를 인메모리에 적재하고,
10초마다 자동 갱신되는 통계/최근 탐지 목록에 반영됩니다.

현재 저장소는 postgres 없이 **api 프로세스 메모리**에만 기록을 쌓습니다(N-01 감사증적의
아주 단순한 v1) — api를 재시작하면 기록이 초기화됩니다. TODO: postgres로 교체.

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

rag-worker와 mcp-server는 각각 `/metrics`에서 `vps_` 접두사 커스텀 메트릭을 노출합니다
(apps/api는 아직 미구현 — "진행 현황" 참고).

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

이 저장소 자체의 `prometheus/prometheus.yml`은 아직 스캐폴딩 단계라(메트릭 목록이 주석으로만
문서화되어 있고 실제 scrape 대상은 미설정) 이 저장소의 grafana(포트 3001)에는 연결되어
있지 않습니다. 위 메트릭을 실제로 수집·시각화하는 쪽은 별도 리포지토리인 gpu-fleet-ops의
Prometheus/Grafana입니다 — 자세한 내용은 위 "재사용한 인프라 스킬" 참고.

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
- [x] F-03 딥보이스 판별 (`apps/api`, 음향 특징 휴리스틱 v1 — 피치 안정성/스펙트럼 평탄도/묵음 규칙성. **정확도 미검증, 실제 데이터로 임계값 보정 필요** — 상세: `infrastructure/adapters/deepvoice_adapter.py` 상단 주석)
- [x] F-06 관제 대시보드 (`apps/frontend`, 탐지 현황 테이블 + 위험도 분포 + 카테고리별 통계 + 통화 분석 폼. `apps/mcp-server/rest_server.py`를 새로 추가해 api가 판정 로직을 HTTP로 호출하도록 연결, api에 인메모리 감사증적 저장소 + 통계 집계 엔드포인트 추가)
- [x] F-07 신고 연동 (`apps/mcp-server`의 `submit_report` 툴 — mock. risk_level이 high면 auto, 그 외엔 manual 채널로 분류해 인메모리에 기록. **실제 112/경찰청 API 호출 없음** — RFP 데이터 제약, `ReportSubmissionService` 상단 주석 참고. 알림 발송은 아직 미구현)
- [ ] `docs/requirements.md`, `docs/design.md`, `docs/test-plan.md` 작성
- [ ] 인프라(`docker-compose.yaml`, `prometheus/prometheus.yml`, `infra/`)는 직접 손으로 채워나가기
- [ ] (진행 중) 모바일 실시간 감지 파이프라인용 STT (`apps/stt-worker`, faster-whisper 기반
      오디오→텍스트 변환. 헥사고날 구조/Prometheus 메트릭(`vps_stt_*`)까지는 완성했으나
      `docker-compose.yaml`/`apps/api` 연동은 아직 — 다음 단계)
<img width="1900" height="1014" alt="Screenshot 2026-08-26 151128_edited" src="https://github.com/user-attachments/assets/5bf57efc-0385-4623-8cec-82461d236ffd" />
<img width="1910" height="1046" alt="Screenshot 2026-08-26 151151_edited" src="https://github.com/user-attachments/assets/4b36260b-be9d-400e-bbbb-15154a82a299" />
