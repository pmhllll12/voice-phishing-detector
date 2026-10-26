# infra/public-demo/ — 개인 PC 공개 데모 (Cloudflare Tunnel)

공모전 심사용으로 https://vps.pmhllll12.cloud 를 개인 PC(WSL2)에서 외부 공개한 구성입니다
(2026-10-26). 클라우드 서버 없이, Cloudflare named tunnel이 PC의 프론트엔드(3001)로
트래픽을 넘기고 프론트엔드가 같은 오리진 경로로 백엔드를 프록시합니다.

```
심사위원 브라우저 ──https──▶ Cloudflare ──tunnel──▶ cloudflared (vps-tunnel.service)
                                                   │
                                                   ▼
                                     next start :3001 (frontend.service)
                                       ├─ /_api/*    → api :8000
                                       └─ /_verify/* → verify-worker :8400 (verify-worker.service)
```

- 프론트엔드는 `NEXT_PUBLIC_API_BASE_URL=/_api`, `NEXT_PUBLIC_VERIFY_WORKER_URL=/_verify`로
  빌드하면 `apps/frontend/next.config.js` rewrites가 내부 백엔드로 프록시합니다(PR #10).
  브라우저는 `localhost` 백엔드를 직접 부르지 않으므로 api/verify-worker는 외부에 노출되지 않습니다.
- verify-worker의 실패 횟수 제한(429)은 cloudflared가 넣는 `X-Forwarded-For` 덕분에
  프록시 뒤에서도 접속자 실IP별로 분리됩니다.
- 3001을 쓰는 이유: 이 PC의 3000은 다른 프로젝트(mini-mes) Grafana가 점유.

## 파일

| 파일 | 설치 위치 |
| --- | --- |
| `systemd/verify-worker.service` | `~/.config/systemd/user/` |
| `systemd/frontend.service` | `~/.config/systemd/user/` |
| `systemd/vps-tunnel.service` | `~/.config/systemd/user/` |
| `cloudflared/vps-detector.yml.example` | `~/.cloudflared/vps-detector.yml` (`<TUNNEL_ID>`, `<USER>` 치환) |
| `frontend.env.production.local.example` | `apps/frontend/.env.production.local` |

api/mcp-server/rag-worker/stt-worker 유닛과 postgres(5433)는 이 구성 이전부터 있던 것이라
여기 포함하지 않았습니다. `frontend.service`의 Node 경로(nvm 버전)는 설치 환경에 맞게 고칩니다.

## 재현 절차

```bash
# 1. 프론트엔드 프로덕션 빌드 (공개용 환경 변수로)
cp infra/public-demo/frontend.env.production.local.example apps/frontend/.env.production.local
(cd apps/frontend && npx next build)

# 2. 터널 생성 + DNS (cert.pem이 있는 Cloudflare 계정, pmhllll12.cloud 존)
cloudflared tunnel create vps-detector
cloudflared tunnel route dns vps-detector vps.pmhllll12.cloud
cp infra/public-demo/cloudflared/vps-detector.yml.example ~/.cloudflared/vps-detector.yml  # 값 치환

# 3. 상시 기동 (재부팅 후에도 뜨도록 linger 필요: loginctl enable-linger $USER)
cp infra/public-demo/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now verify-worker frontend vps-tunnel
```

확인: `https://vps.pmhllll12.cloud/_api/health`, `/_verify/health`가 200이고
`/dashboard?demo=verify`에서 코드 발급→검증이 되면 정상입니다.

## 운영 주의

- 프론트엔드 코드를 바꾸면 `next build` 후 `systemctl --user restart frontend` 해야 반영됩니다(dev 모드 아님).
- PC 전원이 꺼지거나 재부팅/WSL 종료/네트워크 단절 시 접속이 끊깁니다. Windows 절전 "안 함"과
  업데이트 일시 중지를 권장합니다. 상시 가용성이 필요하면 클라우드 배포(Oracle Cloud 예정)로 옮겨야 합니다.
- 내리기: `systemctl --user disable --now vps-tunnel` 후 필요하면
  `cloudflared tunnel delete vps-detector`와 Cloudflare 대시보드에서 `vps` CNAME 삭제.
