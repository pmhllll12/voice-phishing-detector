---
layout: page
title: 용어 정의
permalink: /부록A-용어정의/
---

| 용어 | 설명 |
|---|---|
| 보이스피싱 | 전화·문자를 통해 기관을 사칭하거나 공포를 조성해 금전을 편취하는 사기 수법 |
| 딥보이스(Deepvoice) | AI로 합성하거나 변조한 음성. 실제 사람의 목소리를 흉내 내 신뢰를 얻어내는 데 쓰인다(F-03) |
| RAG (Retrieval-Augmented Generation) | 판정을 내리기 전 관련 문서(이 프로젝트에서는 과거 사기유형 사례)를 검색해 그 내용을 근거로 활용하는 방식(F-04, N-04) |
| MCP (Model Context Protocol) | AI 에이전트가 외부 도구(tool)를 표준화된 방식으로 호출할 수 있게 하는 프로토콜. `apps/mcp-server`가 통화분석/사기패턴DB조회/신고연동 3개 도구를 이 프로토콜로 노출한다 |
| 헥사고날 아키텍처 (Hexagonal Architecture) | domain(순수 모델)→application(유스케이스)→infrastructure(프레임워크/DB) 방향으로만 의존하게 하는 설계 원칙. "포트-어댑터 아키텍처"라고도 부른다 |
| 포트(Port) / 어댑터(Adapter) | 포트는 domain에 정의된 인터페이스(예: `CallAnalysisPort`), 어댑터는 그 인터페이스의 실제 구현체(예: `OllamaCallAnalysisAdapter`). 어댑터를 교체해도 포트를 쓰는 상위 계층은 영향받지 않는다 |
| RBAC (Role-Based Access Control) | 역할 기반 접근통제. 이 프로젝트는 VIEWER(조회)/HANDLER(처리)/ADMIN(관리자) 3단계 계층을 X-API-Key 헤더로 구분한다(N-02) |
| pgvector | PostgreSQL 확장으로, 벡터(임베딩) 컬럼과 코사인 유사도 등 벡터 연산자를 지원한다. F-04 유사사례 검색의 최종(v3) 저장소로 쓴다 |
| append-only | 한 번 기록된 행을 이후 수정·삭제할 수 없는 로그 방식. N-01 감사증적 요구사항을 postgres 트리거로 강제한다 |
| N-04 설명가능성(Explainability) | AI 판정 결과에 "왜 그렇게 판단했는지"를 사람이 검증 가능한 형태로 함께 제공해야 한다는 요구사항. 이 프로젝트의 핵심 차별점("블랙박스 판정 불가") |
| 블랙박스 판정 | 판정 근거 없이 결과(점수/라벨)만 제공하는 방식. 이 프로젝트가 명시적으로 지양하는 방식 |
| SLA (Service Level Agreement) | 서비스 수준 목표. 이 문서에서는 N-05(통화 종료 후 5초 이내 판정)를 가리킨다 |
| 폴백(Fallback) | 주 경로가 실패했을 때 대체 경로로 자동 전환하는 것. 예: Ollama 미가동 시 규칙 기반(v1)으로, GPU 미가용 시 CPU로 자동 전환 |

[← 목차로]({{ "/toc/" | relative_url }})
