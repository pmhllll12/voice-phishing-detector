# infra/ — 배포 뼈대 (직접 채워나갈 부분)

gpu-fleet-ops에서 검증한 AWS EC2 + Cloudflare Tunnel/도메인 연결, Nginx 리버스 프록시,
Full(strict) SSL 구성 경험을 이 프로젝트에도 재사용할 예정입니다. 여기는 의도적으로
스캐폴딩만 해두고 세부 구성은 직접 채워나가는 것을 권장합니다 (포트폴리오 어필 포인트).

## TODO 목록

- [ ] EC2 인스턴스 사양 결정 (postgres+pgvector, 여러 컨테이너를 감안한 스펙)
- [ ] 프로덕션용 Kustomize overlay 분리 (2026-09-07 로컬 오케스트레이션이
      docker-compose에서 k3s(`k8s/` + 루트 `kustomization.yaml`)로 전환됨 —
      `docker-compose.prod.yaml` 대신 `k8s/overlays/prod/`에서 replicas/리소스
      limit/로그 설정 등 프로덕션 차이만 patch로 얹는 방식을 검토할 것)
- [ ] Nginx 리버스 프록시 설정 (`infra/nginx/` 폴더에 conf 작성 — gpu-fleet-ops 설정 참고)
- [ ] Cloudflare Tunnel 설정 (`cloudflared` config.yml, DNS 라우팅)
- [ ] Full(strict) SSL 모드 확인 (Cloudflare ↔ origin 서버 간 인증서)
- [ ] 배포 스크립트 또는 GitHub Actions CI/CD 파이프라인 (.github/workflows/)
- [ ] 시크릿 관리 방식 결정 (.env를 서버에 어떻게 안전하게 전달할지)
- [ ] 감사증적(N-01) 로그의 백업/보존 정책

## 참고

- 이전 프로젝트 gpu-fleet-ops (https://github.com/pmhllll12/gpu-fleet-ops) 의 배포 구성을
  1차 참고 템플릿으로 삼되, 이번 프로젝트는 GPU 메트릭이 아닌 애플리케이션 메트릭 + RAG
  워크로드(postgres+pgvector)가 추가된다는 점을 감안해 리소스 산정을 다시 할 것.
