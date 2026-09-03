# 요구사항정의서 (Requirements Specification)

**사업명**: AI 기반 보이스피싱 실시간 탐지 및 대응 시스템 구축
**기준 문서**: [`docs/RFP.md`](RFP.md) (제안요청서)
**작성일**: 2026-08-31
**작성자**: 박민호 (1인 개발)

> 이 문서는 `docs/RFP.md`가 개조식으로 제시한 요구사항(F-01~F-07, N-01~N-06)을,
> 실제 구현·테스트 근거와 함께 검증 가능한 수용 기준(acceptance criteria) 수준으로
> 구체화한다. RFP가 "무엇을 원하는가"라면 이 문서는 "그것을 어떻게 검증했는가/할
> 것인가"에 해당한다. 각 요구사항 항목의 "구현 현황"은 2026-08-31 기준이며, 근거로
> 든 커밋 해시와 테스트 파일은 실제로 존재하고 통과하는 것들이다(추정치 아님).

## 1. 개요

### 1.1 목적

전화·문자 기반 보이스피싱 피해를 예방하기 위해, 통화/문자 내용을 실시간으로
분석하여 사기 패턴을 탐지하고, 딥보이스(AI 합성 음성) 여부를 판별하며, 유사
사기사례를 근거로 제시하여 탐지 결과의 신뢰성과 설명가능성을 확보하는 AI
시스템을 구축한다(`docs/RFP.md` 1.1).

### 1.2 범위

- **포함**: 통화/문자 텍스트 및 오디오 분석(F-01, F-02, F-05), 딥보이스 판별(F-03),
  유사사례 검색(F-04), 관제 대시보드(F-06), 신고 연동(F-07, mock), 감사증적(N-01),
  접근통제(N-02), 개인정보 비식별화(N-03), 설명가능성(N-04), 응답시간 계측(N-05),
  확장성(N-06).
- **제외**: 실제 112/경찰청 신고 API 연동, 실제 보이스피싱 통화 녹음 데이터 사용,
  EC2/프로덕션 배포(별도 이터레이션), 다국어 지원(한국어 전용).

### 1.3 용어

`jekyll/chapters/부록A-용어정의.markdown`(제안서 사이트) 참고. 핵심 용어만 요약:

| 용어 | 정의 |
|---|---|
| 판정(Verdict) | 통화/문자 1건에 대한 위험도 스코어 + 탐지 패턴 + 근거 설명의 묶음 |
| 감사증적 | N-01이 요구하는, 변경 불가능한(append-only) 판정 기록 |
| 포트/어댑터 | 헥사고날 아키텍처의 인터페이스(포트)와 구현체(어댑터) — `CLAUDE.md` 참고 |

### 1.4 우선순위 표기

RFP 자체가 F-01~F-07/N-01~N-06을 전부 "구현 대상"으로 제시했고 우선순위를 따로
매기지 않았으므로, 이 문서도 전 항목을 동일 우선순위(필수)로 다룬다. 다만 구현
순서는 실제 개발 로그(`jekyll/chapters/07-개발구현계획.markdown` 4절)에 따라
F-01/F-02(핵심 판정)를 먼저, 비기능 요구사항을 나중에 채웠다.

## 2. 기능 요구사항 (F-01~F-07)

### F-01 통화 텍스트 분석

| 항목 | 내용 |
|---|---|
| 설명 | 통화/문자 텍스트에서 기관사칭·공포조성·긴급송금유도·개인정보요구 패턴을 탐지한다 |
| 입력 | 통화/문자 텍스트(문자열), 또는 F-05 경로로 변환된 STT 결과 텍스트 |
| 처리 | mcp-server가 로컬 LLM(Ollama, EXAONE 3.5 2.4B)에 JSON Schema 강제 출력으로 위임. Ollama 미가동/타임아웃/파싱 오류 시 키워드 규칙 기반(v1)으로 자동 폴백 |
| 출력 | 탐지된 패턴 목록(`category`, `category_label`, `matched_keywords`) |
| 수용 기준 | ① 4개 카테고리(기관사칭/공포조성/긴급송금유도/개인정보요구) 중 텍스트에 해당하는 패턴을 최소 1개 이상 탐지한다. ② 정상 대화 텍스트(예: "오늘 점심 메뉴는...")에서는 패턴을 탐지하지 않는다(오탐 없음). ③ Ollama가 죽어 있어도 요청이 실패하지 않고 규칙 기반 결과를 반환한다 |
| 구현 현황 | 완료 — v1(규칙)→v2(LLM, `360ffde`). 합성 데이터셋 26건으로 검증(`767eac1`, 정상 통화 오탐 0건) |
| 검증 근거 | `apps/mcp-server/tests/test_synthetic_dataset_calibration.py`, RBAC 실측(8장 참고) |

### F-02 위험도 스코어링

| 항목 | 내용 |
|---|---|
| 설명 | F-01의 탐지 결과를 바탕으로 0~100점 위험도 스코어를 산출하고 저/중/고 3단계로 분류한다 |
| 입력 | F-01과 동일(같은 LLM 호출에서 함께 산출) |
| 처리 | LLM이 탐지 패턴과 함께 0~100 정수 스코어를 산출. 등급 매핑: **고위험 ≥70, 중위험 ≥40, 저위험 <40**(`RISK_LEVEL_THRESHOLDS`, `apps/mcp-server/src/domain/entities.py`) |
| 출력 | `risk_score`(int, 0~100), `risk_level`(low\|medium\|high) |
| 수용 기준 | ① 스코어가 항상 0~100 범위 안에 있다. ② 등급이 위 임계값과 정확히 일치한다. ③ 동일 카테고리 조합에 대해 반복 호출 시 등급이 뒤집히지 않는다(LLM 확률적 변동은 점수 수준에서는 있을 수 있으나 등급 경계를 자주 넘나들지 않아야 함) |
| 구현 현황 | 완료 — F-01과 통합 구현. 합성 데이터셋 26건으로 카테고리 조합별 등급이 설계 의도대로 나옴을 확인(`767eac1`) |
| 검증 근거 | 실제 라이브 스택 실측(8장 3절 — "금융감독원인데 명의도용..." → 저위험(30)/중위험(50) 등 문맥에 따라 합리적으로 변동함을 확인) |

### F-03 딥보이스 판별

| 항목 | 내용 |
|---|---|
| 설명 | 통화 음성이 AI 합성 음성(딥보이스)인지 판별한다 |
| 입력 | 16-bit PCM WAV 오디오 바이트 |
| 처리 | v2(기본값): HuggingFace `mo-thecreator/Deepfake-audio-detection`(wav2vec2-base)로 분류. 모델 로드/추론 실패 시 v1(음향 특징 휴리스틱 — 피치 안정성/스펙트럼 평탄도/묵음 규칙성)로 자동 폴백. v2 판정 시에도 v1의 3개 지표를 보조 근거로 항상 함께 계산 |
| 출력 | `is_synthetic`(bool\|None), `confidence`(0.0~1.0), `indicators`(list), `explanation`(str) |
| 수용 기준 | ① 판정 근거(indicators)가 항상 최소 1개 이상 포함된다(블랙박스 판정 금지, N-04). ② v2 정상 동작 시 indicators는 4개(모델 판정 1 + 보조 음향지표 3)다. ③ 오디오가 너무 짧거나 무효하면 `is_synthetic=None`(판단 보류)을 반환하고 예외를 던지지 않는다 |
| 구현 현황 | 완료 — v1(임계값 실측 보정, `4b3b0b5`) → v2(오픈소스 모델 교체, `9a231d3`, 서빙 메트릭 `8bef4da`) → **일반화 검증 완료**(2026-09-01): 보정 데이터셋(16건)과 별도인 홀드아웃 48건(TTS 엔진 2종 gTTS/edge-tts × 자연 발화 언어 2종 영어 LibriSpeech/한국어 Zeroth-Korean)에서 전체 47/48(97.9%) — 특히 처음 보는 TTS 엔진(edge-tts)과 한국어 실제 발화 그룹에서 각각 12/12 완벽 분리 |
| 검증 근거 | `apps/api/tests/test_deepvoice_dataset_calibration.py`(v1, 16건), `apps/api/tests/test_wav2vec2_deepvoice_adapter.py`(v2, 재현율 8/8·오탐 0/8 실측), `apps/api/tests/test_deepvoice_generalization.py`(일반화, 48건 홀드아웃) |
| 알려진 한계 | 일반화 검증(48건)으로 "gTTS 특유 아티팩트만 외웠다"/"합성 여부가 아니라 언어를 구분했다"는 두 우려는 실측으로 반증했지만, 여전히 48건 규모라 프로덕션 수준의 일반화를 보장하진 않는다. v2 모델의 학습 데이터셋이 모델 카드에 명시돼 있지 않아 우리 데이터셋과 겹칠 가능성도 완전히 배제 못함(`wav2vec2_deepvoice_adapter.py` 상단 주석) |

### F-04 유사사례 매칭

| 항목 | 내용 |
|---|---|
| 설명 | RAG 기반으로 기존 사기유형 DB에서 통화 내용과 유사한 사례를 검색한다 |
| 입력 | 통화 텍스트(쿼리) |
| 처리 | rag-worker가 sentence-transformers(`jhgan/ko-sroberta-multitask`)로 쿼리를 임베딩한 뒤, postgres(pgvector)의 `fraud_cases` 테이블에서 코사인 유사도(`<=>` 연산자) 상위 K건을 검색 |
| 출력 | `matches`(list of `case_id`, `title`, `category`, `summary`, `source_note`, `similarity`) |
| 수용 기준 | ① 쿼리와 의미적으로 관련 있는 사례가 상위권에 온다(예: "검찰 사칭" 변형 표현 → 검찰 출석요구형 사례가 상위). ② rag-worker가 다운돼도 F-01/F-02 판정 자체는 실패하지 않고 유사사례만 빈 리스트로 폴백한다 |
| 구현 현황 | 완료 — v1(TF-IDF)→v2(로컬 임베딩, `2d60b87`)→v3(postgres+pgvector, `960e96e`) |
| 검증 근거 | README "재사용한 인프라 스킬" 절의 실측 비교(TF-IDF는 무관한 사례를 2위로 고른 반면 임베딩은 정확한 사례를 찾음, 코퍼스 10건 기준) |

### F-05 판정 근거 제시

| 항목 | 내용 |
|---|---|
| 설명 | 왜 보이스피싱으로 판단했는지 자연어로 설명한다(블랙박스 판정 금지) |
| 입력 | F-01/F-02/F-04 결과 |
| 처리 | mcp-server의 `ExplanationService`가 탐지 패턴 + 위험도 + F-04 유사사례를 결합해 요약/상세 설명 문장을 생성. 오디오 입력 시 stt-worker(`/api/v1/transcribe`, faster-whisper)가 먼저 텍스트로 변환한 뒤 동일 경로를 탄다 |
| 출력 | `explanation_summary`(str), `explanation`(str) |
| 수용 기준 | ① 모든 판정에 `explanation`이 비어있지 않다. ② 유사사례가 있으면 근거 문장에 인용된다. ③ 오디오 입력 경로(F-05 확장)가 텍스트 입력과 동일한 판정 품질을 낸다 |
| 구현 현황 | 완료 — 템플릿 기반 생성, F-04 결합(`73ecdb1`), stt-worker 연동(`8d174c1`) |
| 검증 근거 | 라이브 스택 실측(6장 참고) — 마이크 녹음 → stt-worker 변환 → 판정까지 e2e 확인 |

### F-06 관제 대시보드

| 항목 | 내용 |
|---|---|
| 설명 | 실시간 탐지 현황과 통계를 시각화한다 |
| 입력 | api의 `/api/v1/calls`, `/api/v1/stats/summary` |
| 처리 | Next.js 프론트엔드가 10초 폴링으로 조회. N-03에 따라 기본은 마스킹된 텍스트만 노출(ADMIN 키만 원문 열람) |
| 출력 | 탐지 현황 목록, 위험도 분포, 카테고리별 통계, 통화 분석 폼(텍스트/음성 입력) |
| 수용 기준 | ① 새 판정이 발생하면 대시보드에 10초 이내 반영된다(또는 `onAnalyzed` 콜백으로 즉시 반영). ② VIEWER 권한으로는 원문(raw_transcript)이 응답에 포함되지 않는다 |
| 구현 현황 | 완료 — 텍스트 입력 폼(F-01/F-02 경로) + 음성 녹음 버튼(F-05 오디오 경로, `8e28f49`) |
| 검증 근거 | Playwright 기반 실제 브라우저 자동화로 텍스트/음성 두 경로 모두 e2e 검증(스크린샷 포함) |

### F-07 신고 연동

| 항목 | 내용 |
|---|---|
| 설명 | 고위험 판정 시 신고 접수 프로세스를 개시한다 |
| 입력 | `case_summary`, `risk_level` |
| 처리 | mcp-server의 `submit_report`(mock) — `risk_level=high`면 `channel=auto`, 그 외엔 `manual`로 분류해 postgres(N-01)에 기록. **실제 112/경찰청 API는 호출하지 않는다**(RFP 4장 데이터 제약) |
| 출력 | `report_id`, `status`, `channel`, `submitted_at`, `note` |
| 수용 기준 | ① 고위험 판정 행에서 "신고 접수" 버튼이 노출된다(F-06). ② 접수 기록이 append-only로 저장돼 이후 수정/삭제되지 않는다(N-01) |
| 구현 현황 | 완료 — mock 구현(`df98210`) → REST/대시보드 연결(`27a6178`) |
| 검증 근거 | `apps/mcp-server/tests/test_rest_report_endpoint.py`, `apps/api/tests` 내 신고 관련 테스트 |

### 부가기능: 크로스채널 상관관계 탐지 (2026-09-02 추가, RFP 원 범위 밖 차별화 기능)

| 항목 | 내용 |
|---|---|
| 설명 | 동일한 전화번호/계좌번호/URL이 서로 다른 채널(통화/문자/이메일)의 탐지 기록에 시간 윈도우 안에 반복 등장하면 위험도에 가산점을 주고 판정 근거에 인용한다. RFP의 F-01~F-07에는 없는 기능이지만, 시중 보이스피싱 차단 앱이 전부 자기 채널 안에서만 판단한다는 공백을 메우는 이 프로젝트의 차별점이라 별도 항목으로 문서화한다 |
| 입력 | `channel`(call/sms/email), 텍스트(통화 텍스트 또는 문자/이메일 본문) |
| 처리 | mcp-server `correlate_multichannel_signals` — 전화번호/계좌번호/URL을 정규식으로 추출해 `channel_signals`(postgres)에 기록하고, 다른 채널에서 같은 값이 시간 윈도우(기본 30분) 안에 있었는지 조회. 매치 건당 위험도 +15점(상한 30점), F-02 등급 재산정, F-05 근거 문장 추가. `analyze_call_pattern`이 call 채널에 대해 자동으로 결합한다. (선택) URL 엔티티는 Google Safe Browsing API로도 대조해, 악성으로 확인되면 크로스채널 매치 여부와 무관하게 +40점을 별도로 가산한다 |
| 출력 | 매치 목록(채널/엔티티 타입/마스킹된 값/시각), `flagged_urls`(Safe Browsing이 악성으로 확인한 URL), `risk_boost`, 근거 문장 목록, (있으면) 재산정된 `updated_risk_score`/`updated_risk_level` |
| 수용 기준 | ① 다른 채널에 같은 엔티티가 시간 윈도우 안에 기록돼 있으면 매치가 반환되고 위험도가 오른다. ② 채널이 같거나 시간 윈도우 밖이면 매치되지 않는다. ③ 응답에 노출되는 엔티티 값은 항상 마스킹된다(N-03과 같은 원칙 — raw 값은 저장소에만 있고 API로 나가지 않는다). ④ Google Safe Browsing API 키가 없으면 그 검사만 건너뛰고 나머지 기능은 그대로 동작한다 |
| 구현 현황 | 완료 — `apps/mcp-server`(domain/application/infrastructure 전 계층) + `infra/db/init.sql`의 `channel_signals` 테이블 신규 추가. `apps/api`도 N-03 마스킹 "전" 원문에서 엔티티를 추출해 값만 mcp-server로 넘기는 경로(`domain/entity_extraction.py`, `MultichannelCorrelationPort`)를 추가해, 실제 프런트 대시보드가 쓰는 REST 경로에서도 전화번호/계좌번호 상관관계가 정상 동작한다(2026-09-02). apps/api 경유 종단 실측: masked_transcript에 `[계좌번호]` 태그가 찍히면서도 95점→100점(HIGH) 상승 확인. Google Safe Browsing 연동(`ThreatIntelligencePort`/`GoogleSafeBrowsingAdapter`)도 완료 + 실제 API 키로 검증 완료(2026-09-02) — 정상 URL은 매치 없음, Google 공식 테스트 악성 URL(전체 경로)은 정확히 탐지, 같은 URL을 host-only 파이프라인 그대로 태우면 매치가 안 뜨는 것까지(아래 한계가 실측으로 재현됨) 실제 API로 확인함. **email 실채널 연동 + F-06 대시보드 통합 완료(2026-09-02)**: Gmail API 폴링(`GmailEmailSourceAdapter`/`EmailIngestionService`, `scripts/poll_gmail_inbox.py`)이 새 메일을 apps/api의 `POST /api/v1/calls/analyze`(channel="email")로 보내 F-01/F-02/F-05 판정 + channel=email 상관관계에 결합하고, 감사증적(postgres, `call_analysis_results.channel` 컬럼 신규)에 남겨 F-06 대시보드 "이메일" 탭에도 노출한다 — 통화와 완전히 같은 판정/저장 경로를 재사용한다(`AnalyzeCallService.execute()`/mcp-server `CallAnalysisService.execute()` 양쪽에 `channel` 매개변수 추가, 기본값은 기존과 동일해 하위호환). 실측: 실제 Gmail 계정으로 보낸 메일이 위험도 85점으로 판정되어 대시보드 이메일 탭에 뜨는 것까지 확인. SMS는 유료 SMS 게이트웨이가 필요해 설계만 함(`docs/design.md` 7장) |
| 검증 근거 | `apps/mcp-server`: `test_entity_extraction.py`, `test_multichannel_correlation_service.py`, `test_call_analysis_correlation.py`, `test_postgres_channel_signal_repository.py`, `test_rest_correlate_endpoint.py`, `test_multichannel_synthetic_scenarios.py`(합성 시나리오 4건), `test_google_safe_browsing_adapter.py`(httpx.post monkeypatch로 요청/응답/폴백 검증), `test_gmail_email_source_adapter.py`(가짜 Gmail API 응답으로 파싱/조회/처리완료표시), `test_email_ingestion_service.py`(오케스트레이션). `apps/api`: `test_entity_extraction.py`, `test_analyze_call_correlation.py`(N-03 마스킹 전/후 엔티티 추출 회귀 가드 포함) |
| 알려진 한계 | SMS 실채널 연동은 범위 밖(설계만) — `correlate_multichannel_signals` 툴로 합성 이벤트를 수동 주입해 검증하는 것으로 대체. Google Safe Browsing은 host-only 정규화 때문에 특정 경로만 악성으로 등재된 URL은 놓칠 수 있음(실측으로 재현 확인, `docs/design.md` 7장 참고) — 키가 없으면 자동으로 이 검사만 건너뛴다. email(Gmail API)은 의도한 테스트 계정으로 OAuth→폴링→판정까지 전부 재검증 완료(2026-09-02) — 첫 시도에서 계정 선택 실수로 실제 메일 약 100통이 읽음 처리됐다가 즉시 복구된 사고가 있었고, 이후 처리 상태 추적을 UNREAD 라벨 제거에서 전용 라벨 추가 방식으로 재설계한 뒤 올바른 계정으로 재검증해 UNREAD가 안 바뀜을 직접 확인함(`docs/design.md` 7장 참고) |

## 3. 비기능 요구사항 (N-01~N-06)

### N-01 감사증적

| 항목 | 내용 |
|---|---|
| 설명 | 모든 판정 과정을 변경 불가능한(append-only) 로그로 기록한다 |
| 수용 기준 | ① `call_analysis_results`/`report_records` 테이블에 UPDATE/DELETE를 시도하면 postgres가 예외로 거부한다(애플리케이션 코드가 아니라 DB 트리거 레벨). ② 감사증적 저장소(postgres)가 죽으면 `/ready`가 503을 반환한다(우회 경로 없음을 명시적으로 알림) |
| 구현 현황 | 완료 — `infra/db/init.sql`의 `reject_audit_log_mutation()` 트리거(`bd68902`) |
| 검증 근거 | 트리거 SQL 직접 확인 가능(부록D 데이터베이스 ERD, `jekyll/chapters/부록D-데이터베이스ERD.markdown` D.5) |

### N-02 접근통제 (RBAC)

| 항목 | 내용 |
|---|---|
| 설명 | 조회(VIEWER)/처리(HANDLER)/관리자(ADMIN) 3단계 권한을 X-API-Key 헤더로 분리한다 |
| 수용 기준 | ① 키 없음/미등록 키 → 401. ② 권한 부족 → 403. ③ 충분한 권한 → 200. ④ health/ready/metrics는 인증 예외(인프라 컴포넌트 전용) |
| 구현 현황 | 완료 — apps/api 도입(`a9480fd`) → mcp-server REST 어댑터까지 확장(`c9799af`), 서비스간 인증(`MCP_SERVICE_API_KEY`) 포함 |
| 검증 근거 | **실측 완료**(2026-08-31) — mcp-server `/api/v1/analyze`, `/api/v1/reports`에 대해 401/403/200 전 케이스를 라이브 스택에 curl로 직접 확인. 과정에서 postgres 다운으로 인한 500 이슈를 실제로 발견/해결한 사례까지 있음(`jekyll/chapters/08-테스트및검증계획.markdown` 2절) |

### N-03 개인정보 비식별화

| 항목 | 내용 |
|---|---|
| 설명 | 통화 내용 중 개인정보(이름/계좌번호/전화번호/주민등록번호)를 마스킹한다 |
| 수용 기준 | ① mcp-server(LLM 포함) 호출 전에 마스킹이 적용된다. ② VIEWER/HANDLER 권한 응답에는 `masked_transcript`만 포함되고 `raw_transcript`는 없다. ③ ADMIN 권한 응답에는 둘 다 포함된다 |
| 구현 현황 | 완료 — `apps/api/src/domain/pii_masking.py`(정규식 기반 v1), N-02와 결합(`0f6440f`). **이름 마스킹 정량 평가 완료**(2026-09-01) — 라벨 28건(`data/pii_masking_eval.json`)으로 측정한 정밀도 0.615/재현율 0.727을, 실측된 오탐 단어(고객님/이용자님/신청자님 등 10건) 블록리스트로 보정해 정밀도 1.0(재현율은 그대로 0.727)으로 개선 |
| 검증 근거 | `apps/api/tests/test_pii_masking.py`(형식 커버리지) + `apps/api/tests/test_pii_masking_eval.py`(정밀도/재현율 회귀 가드) |
| 알려진 한계 | 재현율이 100%가 아닌 이유 3가지를 실측으로 확인: ① 성씨 목록 밖의 성(표/위/선우 등), ② 호칭이 이름이 아니라 직함에 붙는 경우("김민수 대리님"), ③ 호칭 없는 반말 호명("민수야"). 오탐 블록리스트도 실측된 사례만 등재해 완전하지 않음(`domain/pii_masking.py` 상단 주석) |

### N-04 설명가능성

| 항목 | 내용 |
|---|---|
| 설명 | 모든 판정에 추적 가능한 근거를 제공한다(블랙박스 판정 불가) — 이 프로젝트의 핵심 차별점 |
| 수용 기준 | ① F-01~F-03 모든 판정 결과에 근거(탐지 패턴/음향 지표/모델 판정 등)가 최소 1개 포함된다. ② 근거가 사람이 읽고 검증 가능한 자연어/구조화된 형태다(원시 확률값만 노출하지 않는다) |
| 구현 현황 | 완료 — F-05(자연어 설명) + F-04(유사사례) 결합, F-03 v2도 모델 판정과 별개로 음향 지표를 보조 근거로 유지 |
| 검증 근거 | `test_verdicts_always_include_explanation_for_n04`(F-03 v1), `test_verdicts_combine_model_and_heuristic_indicators_for_n04`(F-03 v2) |

### N-05 응답시간

| 항목 | 내용 |
|---|---|
| 설명 | 통화 종료 후 평균 5초 이내에 판정 결과를 산출한다 |
| 수용 기준 | ① `vps_analysis_duration_seconds` 히스토그램이 판정 성공 경로에서 기록된다(에러 경로는 제외 — 가용성 문제와 SLA 위반을 구분). ② F-03 v2도 별도 메트릭(`vps_deepvoice_inference_duration_seconds`)으로 계측된다 |
| 구현 현황 | 계측 배선(`1414f30`, `8bef4da`) + **실트래픽 SLA 검증 완료**(2026-09-01). 단일 요청(순차 26건): 평균 2.11초, p95 2.81초 — SLA(평균 5초 이내) 충족. 동시 요청 4건(78건, 3라운드)에서는 평균 8.75초로 미충족(94.9%가 5초 초과) — 원인을 mcp-server/rag-worker의 "동기 블로킹 호출이 async 이벤트 루프를 막아 우발적으로 전체 직렬화되는" 소프트웨어 문제와 "GPU 1장(RTX 3050)의 처리 용량" 인프라 문제로 분리 진단. **동시성 SLA 해결 시도**(같은 날): `run_in_threadpool`+`asyncio.Semaphore`로 전자를 고쳐 꼬리 지연(p95/p99/최대)을 30~40% 개선(최대 22.1초→11~14초대)했지만, 평균 지연(8.1~8.3초)과 SLA 위반 비율(96~99%)은 거의 그대로 — 후자(GPU 용량)가 진짜 병목임을 확정했다. GPU 증설 또는 수요 측 속도제한/큐잉은 미도입(`docs/test-plan.md` N-05 절 참고) |
| 검증 근거 | 실제 `/api/v1/calls/analyze`에 대한 반복 부하테스트(수정 전/후, LLM_MAX_CONCURRENCY 1/2/4 각각) + Prometheus `histogram_quantile` 교차검증 + `test_llm_concurrency_limit.py`(세마포어 동작 회귀 가드). Grafana 대시보드에 p95/p99 패널 추가(`gpu-fleet-ops/dashboards/gpu-fleet-monitoring.json`) |

### N-06 확장성

| 항목 | 내용 |
|---|---|
| 설명 | 신규 사기유형 추가 시 시스템 재설계 없이 확장 가능한 구조로 설계한다 |
| 수용 기준 | ① 포트(인터페이스)를 유지한 채 어댑터(구현체)를 교체할 수 있다 — application 계층 diff 0줄. ② 새 카테고리 추가 시 `PatternCategory` enum + `PATTERN_RULES` dict 확장만으로 충분하다(코드 재설계 불필요) |
| 구현 현황 | 완료 — **어댑터 교체 4개 축**: F-01/F-02 판정 알고리즘(규칙→LLM), F-04 검색 알고리즘(TF-IDF→임베딩→pgvector), N-01 감사증적 저장소(인메모리→postgres), F-03 딥보이스 판별기(휴리스틱→wav2vec2). **+ 신규 진입점 추가 축**(2026-09-01): mcp-server에 gRPC를 3번째 진입점으로 추가(`grpc_server.py`), N-02 RBAC도 grpc metadata로 재사용. 매번 application 계층 diff 0줄이 커밋 메시지로 실측됨. **+ 스키마 확장 축**(2026-09-02): 크로스채널 상관관계 탐지가 "완전히 새로운 질의 축"이 필요해 `channel_signals` 테이블을 새로 추가한 사례 — 앞의 4개 축(애플리케이션 계층만 교체)과 달리, 이 축은 스키마 변경이 정직하게 필요함을 보여준다(`docs/design.md` 7장 참고) |
| 검증 근거 | [`docs/design.md`](design.md) N-06 확장성 설계 챕터 — 커밋 해시까지 명시된 표 |

## 4. 요구사항 추적표 (Traceability Matrix)

| ID | 핵심 구현 파일 | 테스트 파일 | 완료 커밋 |
|---|---|---|---|
| F-01/F-02 | `apps/mcp-server/src/infrastructure/adapters/ollama_call_analysis_adapter.py` | `test_synthetic_dataset_calibration.py` | `360ffde`, `767eac1` |
| F-03 | `apps/api/src/infrastructure/adapters/wav2vec2_deepvoice_adapter.py` | `test_wav2vec2_deepvoice_adapter.py` + `test_deepvoice_generalization.py`(일반화, 48건) | `9a231d3`, `8bef4da` |
| F-04 | `apps/rag-worker/src/infrastructure/adapters/pgvector_similarity_adapter.py` | `test_pgvector_similarity_adapter.py` | `960e96e` |
| F-05 | `apps/api/src/application/services.py`(`TranscribeAndAnalyzeCallService`) | — (e2e로 검증) | `8d174c1` |
| F-06 | `apps/frontend/src/app/page.tsx`, `AnalyzeCallForm.tsx` | — (Playwright e2e) | `8e28f49` |
| F-07 | `apps/mcp-server/src/application/services.py`(`ReportSubmissionService`) | `test_rest_report_endpoint.py` | `27a6178` |
| N-01 | `infra/db/init.sql` | `test_postgres_call_log_repository.py`, `test_postgres_report_repository.py` | `bd68902` |
| N-02 | `apps/api/src/infrastructure/adapters/api_key_role_auth.py` | `test_rbac.py`(양쪽 앱) | `a9480fd`, `c9799af` |
| N-03 | `apps/api/src/domain/pii_masking.py` | `test_pii_masking.py` + `test_pii_masking_eval.py`(정량 평가) | `0f6440f` |
| N-04 | (F-03/F-05에 걸쳐 구현) | 위 F-03/F-05 테스트에 포함 | — |
| N-05 | `apps/api/src/infrastructure/metrics.py` | 실트래픽 104건 부하테스트(단일요청/동시성4) + Prometheus 교차검증 | `1414f30`, `8bef4da` |
| N-06 | 전체 포트-어댑터 구조 + `apps/mcp-server/src/grpc_server.py` | (각 축의 어댑터 테스트로 간접 검증) + `test_grpc_server.py`(신규 진입점 직접 검증) | `docs/design.md` 참고 |

## 5. 제약사항 및 가정

`docs/RFP.md` 4장과 동일:

- 실제 보이스피싱 통화 녹음 데이터는 사용하지 않는다. 모든 검증 데이터셋은 공개
  자료(뉴스/경찰청 공개자료/gTTS/LibriSpeech)로 직접 제작했다.
- 딥보이스 판별은 "모델을 직접 만드는 것"이 아니라 "판별 근거를 해석 가능한
  형태로 제공하는 것"이 평가 기준이다.
- F-07은 mock이며 실제 112/경찰청 API를 호출하지 않는다.
- 1인 개발 전제 — 조직/역할 분담 관련 요구사항은 해당 없음.
