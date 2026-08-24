# CLAUDE.md

이 프로젝트는 AI 데이터센터/AI 인프라 엔지니어 직무 취업을 위한 개인 포트폴리오 프로젝트입니다.
자세한 배경은 `docs/RFP.md`를 참고하세요.

## 아키텍처 원칙

- 헥사고날 아키텍처 준수: 각 앱(`apps/api`, `apps/mcp-server`, `apps/rag-worker`)은
  `domain/` (프레임워크 비의존 비즈니스 모델) → `application/` (유스케이스) →
  `infrastructure/` (DB, 외부 API, 프레임워크 진입점) 순서로 의존한다.
  즉 domain은 아무것도 import하지 않고, application은 domain만 알고,
  infrastructure가 application/domain을 사용한다. 역방향 의존은 지양한다.
- 커스텀 Prometheus 메트릭 이름은 `vps_` 접두사로 통일한다 (`prometheus/prometheus.yml` 참고).
- 모든 AI 판정에는 N-04(설명가능성) 요구사항에 따라 근거를 함께 반환해야 한다.
  "블랙박스 판정 불가"가 이 프로젝트의 핵심 차별점이다.

## 진행 상태

이 저장소는 스캐폴딩 단계다. 각 파일의 TODO 주석이 다음 구현 우선순위를 나타낸다.
한 번에 다 구현하지 말고, 기능 요구사항(F-01~F-07) 순서대로 단계적으로 채워나갈 것.

## 데이터

실제 보이스피싱 통화 녹음은 사용 금지. 뉴스/경찰청 공개자료 기반의 합성 시나리오
데이터셋을 직접 제작한다 (`docs/RFP.md` 4장 참고).
