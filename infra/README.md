# infra/ — 배포 뼈대 (직접 채워나갈 부분)

gpu-fleet-ops에서 검증한 AWS EC2 + Cloudflare Tunnel/도메인 연결, Nginx 리버스 프록시,
Full(strict) SSL 구성 경험을 이 프로젝트에도 재사용할 예정입니다. 여기는 의도적으로
스캐폴딩만 해두고 세부 구성은 직접 채워나가는 것을 권장합니다 (포트폴리오 어필 포인트).

## TODO 목록

- [ ] EC2 인스턴스 사양 결정 (postgres+pgvector, 여러 컨테이너를 감안한 스펙)
- [x] 프로덕션용 Kustomize overlay 분리 (2026-09-07, `k8s/overlays/prod/`) —
      api/frontend replicas 2, 전 서비스 CPU/메모리 requests·limits, api/
      stt-worker/frontend는 `--reload`/`next dev` 대신 프로덕션 실행 방식으로
      command 오버라이드. 렌더(`kubectl kustomize --load-restrictor
      LoadRestrictionsNone k8s/overlays/prod`) + server-side dry-run(실 k3s API
      서버 스키마 검증)까지 확인, 실제 apply는 아직 안 함(로컬 데모 클러스터
      용량 밖 — Oracle Cloud 실배포 때 적용 예정). 겪은 문제: 오버레이가 루트
      kustomization.yaml을 base로 참조하면 kustomize가 "cycle detected"로
      거부한다(오버레이 디렉터리가 base의 하위 경로라서, `--load-restrictor`로도
      안 풀림) — 그래서 같은 리소스 파일·generator를 오버레이에 재선언하는
      방식으로 우회(k8s/overlays/prod/kustomization.yaml 상단 주석 참고, DRY
      위반이 트레이드오프). 리소스 값은 러프한 추정치라 실배포 후 재조정 필요.
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
