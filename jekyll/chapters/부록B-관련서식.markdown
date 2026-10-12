---
layout: page
title: 관련 서식 — API 명세
permalink: /부록B-관련서식/
---

이 프로젝트는 실제 사업 신청서/공문 같은 행정 서식을 다루지 않는다. 대신 "관련 서식"
자리에, 각 서비스가 실제로 노출하는 **REST API 엔드포인트 전체 목록**을 정리했다 —
개발자가 이 시스템을 연동할 때 참조하는 실질적인 명세서 역할을 한다(전체 소스는
`apps/*/src/main.py` 또는 `apps/mcp-server/src/rest_server.py` 참고).

## B.1 apps/api (포트 8000) — 탐지 오케스트레이션

| Method | Path | 최소 권한 | 설명 |
|---|---|---|---|
| GET | `/health` | 없음 | liveness. 항상 `{"status":"ok"}` |
| GET | `/ready` | 없음 | mcp-server/postgres/stt-worker 의존성 확인. 하나라도 실패 시 503 |
| POST | `/api/v1/calls/analyze` | HANDLER | 통화 텍스트 분석 (F-01/F-02/F-05). Body: `{transcript}` |
| POST | `/api/v1/calls/analyze-audio` | HANDLER | 오디오 업로드 → stt-worker 변환 → 동일 판정 경로 (F-05) |
| GET | `/api/v1/calls` | VIEWER | 최근 판정 목록 (F-06). Query: `limit` |
| GET | `/api/v1/stats/summary` | VIEWER | 위험도/카테고리별 집계 통계 (F-06) |
| POST | `/api/v1/calls/deepvoice-check` | HANDLER | 오디오 업로드 → 딥보이스 판별 (F-03) |
| POST | `/api/v1/reports` | HANDLER | 신고 접수(mock) 요청 (F-07). Body: `{case_summary, risk_level}` |
| GET | `/metrics` | 없음 | Prometheus 스크레이핑 대상 |

## B.2 apps/mcp-server (포트 8100, REST 어댑터)

| Method | Path | 최소 권한 | 설명 |
|---|---|---|---|
| GET | `/health` | 없음 | liveness |
| GET | `/ready` | 없음 | 의존 서비스(Ollama 등) 확인 |
| POST | `/api/v1/analyze` | HANDLER | apps/api가 호출하는 통화 판정 엔드포인트 (F-01/F-02) |
| POST | `/api/v1/reports` | HANDLER | 신고 접수(mock) (F-07) |
| GET | `/metrics` | 없음 | Prometheus 스크레이핑 대상 |

동일한 애플리케이션 로직이 **MCP stdio 진입점**(`server.py`, 인증 없음 — 로컬 신뢰
실행 경로)으로도 노출되며, Claude Code가 이 저장소 루트의 `.mcp.json`을 통해
`analyze_call_pattern` / `lookup_fraud_pattern_db` / `submit_report` 3개 도구로
직접 호출한다.

## B.3 apps/rag-worker (포트 8200)

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | liveness — `corpus_size`, `embedding_model`, `device` 포함 |
| GET | `/ready` | 임베딩 모델 로드 상태 확인 |
| POST | `/api/v1/similar-cases` | 쿼리 텍스트로 유사 사기사례 검색 (F-04) |
| GET | `/metrics` | Prometheus 스크레이핑 대상 |

## B.4 apps/stt-worker (포트 8300)

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | liveness — `model`, `device`, `compute_type` 포함 |
| GET | `/ready` | 모델 워밍업 상태 확인 |
| POST | `/api/v1/transcribe` | 오디오 청크 → 텍스트 변환 (F-05 오디오 경로) |
| GET | `/metrics` | Prometheus 스크레이핑 대상 |

## B.5 로컬 개발용 API 키 (N-02, 프로덕션에서는 반드시 교체)

| 키 | 역할 |
|---|---|
| `dev-viewer-key` | VIEWER — 조회만 가능 |
| `dev-handler-key` | HANDLER — 조회 + 처리(분석/신고 실행) 가능. apps/api가 mcp-server를 호출할 때도 이 값을 서비스 자격증명으로 사용 |
| `dev-admin-key` | ADMIN — 전체 권한 + PII 원문(raw_transcript) 열람 |

[← 목차로]({{ "/toc/" | relative_url }})
