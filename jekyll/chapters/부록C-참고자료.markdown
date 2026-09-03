---
layout: page
title: 참고 자료
permalink: /부록C-참고자료/
---

## C.1 이 저장소의 원본 문서

- [`docs/RFP.md`](https://github.com/pmhllll12/voice-phishing-detector/blob/main/docs/RFP.md) — 이 문서의 모든 F-01~F-07/N-01~N-06 요구사항 원문
- [`docs/design.md`](https://github.com/pmhllll12/voice-phishing-detector/blob/main/docs/design.md) — N-06(확장성) 설계, 포트-어댑터 교체 실증 표
- [`README.md`](https://github.com/pmhllll12/voice-phishing-detector) — 아키텍처 개요, 로컬 실행 가이드
- [`CLAUDE.md`](https://github.com/pmhllll12/voice-phishing-detector/blob/main/CLAUDE.md) — 헥사고날 아키텍처 원칙, 진행 방식

## C.2 사용한 모델/라이브러리

| 구성요소 | 모델/라이브러리 | 용도 |
|---|---|---|
| 판정(F-01/F-02, v2) | Ollama · EXAONE 3.5 2.4B Instruct (Q4_K_M) | 통화 텍스트 패턴 분석, JSON Schema 강제 출력 |
| 유사사례 검색(F-04, v2/v3) | sentence-transformers · `jhgan/ko-sroberta-multitask` | 768차원 한국어 문장 임베딩, pgvector 코사인 유사도로 검색 |
| 모바일 STT(F-05) | faster-whisper (CTranslate2 기반 Whisper) | 오디오 청크 → 텍스트 변환 |
| 딥보이스 판별(F-03, v2) | HuggingFace Hub · `mo-thecreator/Deepfake-audio-detection` (wav2vec2-base 파인튜닝) | AI 합성 음성 여부 판별 (기본값). v1(자체 휴리스틱 — 피치 안정성/스펙트럼 평탄도/묵음 규칙성, numpy 기반)은 폴백 겸 N-04 보조 지표로 유지 |

## C.3 재사용한 이전 프로젝트

- [gpu-fleet-ops](https://github.com/pmhllll12/gpu-fleet-ops) — Docker Compose 구성,
  Prometheus/Grafana 관측성 스택, 헥사고날 아키텍처, AWS EC2 배포, Cloudflare Tunnel
  연동, Claude Code + MCP 서버 설정 패턴을 이 프로젝트에 그대로 재사용했다. rag-worker의
  `vps_rag_*` 메트릭도 gpu-fleet-ops 저장소의 Prometheus 스택에 별도 scrape job으로
  통합 관측 중이다(README "재사용한 인프라 스킬" 참고).

## C.4 데이터 출처

실제 보이스피싱 통화 녹음은 사용하지 않는다는 RFP 4장 제약에 따라, 모든 학습/검증
데이터는 아래 원칙으로 직접 제작했다.

- F-01/F-02 합성 통화 시나리오 — 뉴스·경찰청 공개자료 기반으로 직접 작성한 시나리오 텍스트
- F-03 딥보이스 판별 데이터셋 — 공개 TTS(gTTS) 합성 음성 8건 + 공개 인간 발화 코퍼스
  (LibriSpeech) 8건, 총 16건

## C.5 프로토콜/도구

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — `apps/mcp-server`가
  Claude Code에 도구를 노출하는 데 사용
- [pgvector](https://github.com/pgvector/pgvector) — PostgreSQL 벡터 검색 확장

[← 목차로]({{ "/toc/" | relative_url }})
