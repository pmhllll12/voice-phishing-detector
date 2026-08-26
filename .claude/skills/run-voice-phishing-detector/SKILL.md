---
name: run-voice-phishing-detector
description: Build, run, and drive the voice-phishing-detector full local stack (rag-worker, stt-worker, mcp-server, api, frontend) and take a screenshot of the F-06 dashboard actually detecting a scam call. Use when asked to run/start/launch this project locally, test the dashboard, take a screenshot, or verify the F-01/F-02/F-04/F-06 pipeline end-to-end.
---

This is a 5-process local system (no docker-compose yet — `docker-compose.yaml` is
still a skeleton, see README). Start each process, then drive the frontend with the
Playwright script at `.claude/skills/run-voice-phishing-detector/driver.mjs` — it
fills the "통화 분석해보기" form and screenshots the result. All paths below are
relative to the repo root.

## Prerequisites

No system packages needed beyond what's already in this container (Node, Python 3.14,
an NVIDIA GPU + driver). Each `apps/*/` already has its own `.venv` — if one is
missing, create it with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
inside that app's directory.

Ollama must already be running (mcp-server's LLM calls depend on it):

```bash
curl -s http://localhost:11434/api/version   # must return JSON, not connection-refused
# if not running and it's a systemd user service here: systemctl --user start ollama
```

## Setup

Driver dependencies (one-time, this directory only — not part of the app):

```bash
cd .claude/skills/run-voice-phishing-detector
npm install                    # installs playwright
npx playwright install chromium   # NOT --with-deps: this container has no sudo TTY,
                                   # and --with-deps fails on "sudo: a terminal is
                                   # required". Without --with-deps it just fetches the
                                   # browser binary, which is all this driver needs.
```

## Run (agent path)

Start all 5 services, in this order (each is `nohup ... & disown` so it survives
between tool calls):

```bash
# 1) rag-worker (8200) — usually already running as a systemd user service here
systemctl --user start rag-worker 2>/dev/null || true
curl -sf http://localhost:8200/health || {
  cd apps/rag-worker && nohup .venv/bin/uvicorn src.main:app --port 8200 > /tmp/rag-worker.log 2>&1 & disown
}

# 2) stt-worker (8300) — NOT a systemd service, always start manually.
#    Needs cuBLAS/cuDNN on LD_LIBRARY_PATH or it silently runs on CPU (see Gotchas).
cd apps/stt-worker
export LD_LIBRARY_PATH="$(pwd)/.venv/lib/python3.14/site-packages/nvidia/cublas/lib:$(pwd)/.venv/lib/python3.14/site-packages/nvidia/cudnn/lib"
nohup .venv/bin/uvicorn src.main:app --port 8300 > /tmp/stt-worker.log 2>&1 & disown
cd -

# 3) mcp-server REST adapter (8100)
cd apps/mcp-server && nohup .venv/bin/uvicorn rest_server:app --app-dir src --port 8100 > /tmp/mcp-server.log 2>&1 & disown
cd -

# 4) api (8000) — defaults to MCP_SERVER_URL=http://localhost:8100, no env needed
cd apps/api && nohup .venv/bin/uvicorn src.main:app --port 8000 > /tmp/api.log 2>&1 & disown
cd -

# 5) frontend — defaults to NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
cd apps/frontend && nohup npm run dev > /tmp/frontend.log 2>&1 & disown
cd -
```

Poll instead of sleeping, then read the frontend's actual port from its log (it
auto-bumps off 3000 — see Gotchas):

```bash
timeout 30 bash -c 'until curl -sf http://localhost:8200/health >/dev/null; do sleep 1; done'
timeout 30 bash -c 'until curl -sf http://localhost:8300/health >/dev/null; do sleep 1; done'
timeout 30 bash -c 'until curl -sf http://localhost:8100/health >/dev/null; do sleep 1; done'
timeout 30 bash -c 'until curl -sf http://localhost:8000/health >/dev/null; do sleep 1; done'
timeout 30 bash -c 'until grep -q "Local:" /tmp/frontend.log; do sleep 1; done'
grep "Local:" /tmp/frontend.log   # -> the real frontend URL (3000 or 3001)
```

Drive it — submits one scam-call text through the real form and screenshots
before/after:

```bash
cd .claude/skills/run-voice-phishing-detector
node driver.mjs http://localhost:<port-from-above> "은행 직원인데 대출 상담 위해 개인정보랑 계좌 비밀번호를 알려달라고 문자가 왔어요"
```

Screenshots land in `.claude/skills/run-voice-phishing-detector/screenshots/`
(`01-initial.png`, `02-after-submit.png`). The script also prints the rendered
dashboard text and any browser console errors to stdout — check both before
declaring success, not just that the process exited 0.

Stop everything (`fuser`, not `lsof -ti` — see Gotchas):

```bash
for p in 8300 8100 8000; do fuser -k $p/tcp 2>/dev/null; done
FRONTEND_PORT=$(grep -oP 'localhost:\K[0-9]+' /tmp/frontend.log | tail -1)
fuser -k "${FRONTEND_PORT:-3000}/tcp" 2>/dev/null
# rag-worker is systemd — leave it running, or: systemctl --user stop rag-worker
```

## Run (human path)

Same 5 commands as above, each in its own terminal without `nohup`/`&`, then open
the frontend URL in a real browser and use the form. Ctrl-C each terminal to stop.

## Test

No test suite exists yet in any of the 5 apps as of this writing.

---

## Gotchas

- **stt-worker reports `device: cuda` even when it can't actually use the GPU** unless
  `LD_LIBRARY_PATH` above is set — the pip wheel for faster-whisper/ctranslate2 doesn't
  bundle cuBLAS, and this container has no system-wide `libcublas.so.12`. As of this
  writing the adapter (`apps/stt-worker/src/infrastructure/adapters/faster_whisper_adapter.py`)
  warms up with a real inference call at startup and falls back to CPU if that fails, so
  `curl http://localhost:8300/health` is honest either way — but you only get GPU if the
  path above is set before launch.
- **Frontend port is not reliably 3000 in this container.** A `gpu-fleet-ops-grafana`
  Docker container (unrelated project) already binds `0.0.0.0:3000`, so Next.js silently
  bumps to 3001. Always read the actual port from `/tmp/frontend.log`'s `Local:` line —
  don't hardcode 3000 in the driver invocation.
- **apps/api's audit trail is in-memory only** (no postgres yet — see README). Re-running
  the driver against a stack that already has prior data will NOT show a fresh "고위험"
  string appearing (it's already there from the last run), so the driver checks the "총
  분석 건수" tile's number incrementing, not text presence. If you write your own smoke
  check, do the same — checking for risk-level text alone gives a false pass on a repeat
  run.
- **`npx playwright install chromium --with-deps` fails here** with "sudo: a terminal is
  required for authentication" (no interactive sudo in this container). Drop `--with-deps`
  — the browser binary alone is enough for this driver; no missing shared libs were hit
  running headless Chromium with `--no-sandbox`.
- **`lsof -ti:PORT` misses Next.js's listener in this container** (it found nothing for
  the frontend's port even with `ss -tlnp` confirming something was listening there;
  worked fine for the plain uvicorn processes). Use `fuser -k PORT/tcp` instead, which
  killed it reliably in every test here.
- **mcp-server's first LLM call can be slow** (Ollama cold-start loading the model onto
  GPU, up to ~10s+) — `apps/api`'s timeout to mcp-server was bumped 10s→30s for this
  reason (see git history). The driver waits up to 25s for the count to increment;
  don't shorten that.

## Troubleshooting

- **`curl http://localhost:8000/health` connection refused after starting api**: check
  `/tmp/api.log` — it fails fast with a clear message if mcp-server (8100) isn't up yet;
  start mcp-server first and restart api.
- **Driver prints `WARNING: 총 분석 건수가 늘지 않았습니다`**: the POST to
  `/api/v1/calls/analyze` didn't complete in 25s or errored. Check `/tmp/api.log` and
  `/tmp/mcp-server.log` for the actual request — most likely Ollama isn't running
  (`curl http://localhost:11434/api/version`) or is still cold-starting.
- **stt-worker `/health` shows `"device":"cpu"` unexpectedly**: `LD_LIBRARY_PATH` wasn't
  set before launch, or points at the wrong venv's site-packages. Re-check the export
  line matches the venv you're actually launching (`pwd` inside `apps/stt-worker` at
  export time).
