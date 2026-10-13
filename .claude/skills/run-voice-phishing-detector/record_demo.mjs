// 역방향 신원확인 POC(모의) 시연 영상 녹화 — capture_poc.mjs와 같은 시연 경로를 사람이 보는
// 속도로 한 창(1440x900)에서 진행하며 녹화하고, 장면마다 오른쪽 위에 설명 자막을 붙인다.
// 실제 모바일신분증과 연동하지 않는 모의 시제품 화면이다.
//
// Usage:
//   node record_demo.mjs <frontend-url> [out.mp4]
//
// 전제: SKILL.md "Run (agent path)"대로 postgres + 백엔드 5개 + frontend가 떠 있어야 한다.
// mp4 변환에 ffmpeg가 필요하다(없으면 Playwright 원본 .webm만 남긴다).
//
// 장면(약 1분 30초):
//   ① 탐지        /dashboard?demo=verify 자동 분석 → 상대 신원 확인 권장
//   ② 정상 직원   대시보드 직원 휴대폰(모의)에서 코드 생성 → 고객 휴대폰(모의)에 입력 → 확인됨,
//                 대시보드 표의 "신원확인됨" 배지
//   ③ 사칭범      새 통화의 국민 화면에서 000000(재입력 안내) → 000001(확인 불가 + 보호자 알림(모의))
//                 — 대시보드 화면에 앞 장면의 진짜 코드가 남아 있으면 헷갈려서 국민 화면 단독으로 한다
//   ④ 퇴사자      새 자격증명 발급 → 코드 생성 → 폐기 후 그 코드 입력 → 확인 불가
//                 (시드 demo-bank-staff는 폐기하지 않는다)
//   ⑤ 방문 QR     □□도시가스(모의) 방문 코드·QR → /verify/citizen?code=… 미리 채움 → 확인하기 → 확인됨
//
// 실패 횟수 제한 주의: 한 번 녹화에 틀린 코드 3회(사칭범 2 + 퇴사자 1)를 쓴다. 10분 안에 다시
// 녹화하면 429(rate_limited)에 걸려 장면이 달라지므로 api와 verify-worker를 재시작한 뒤 돌릴 것
// (SKILL.md "Rate limit gotcha" 참고). 결과가 기대와 다르면 바로 실패로 끝낸다.

import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [, , URL_, outArg] = process.argv;
if (!URL_) {
  console.error("usage: node record_demo.mjs <frontend-url> [out.mp4]");
  process.exit(1);
}
const VW = process.env.VW || "http://localhost:8400";
const API = process.env.API || "http://localhost:8000";
const API_KEY = process.env.API_KEY || "dev-handler-key";
const OUT = path.resolve(outArg || "demo.mp4");
const VIDEO_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "record-demo-"));
// AnalyzeCallForm.tsx AUTHORITY_IMPERSONATION_EXAMPLE과 같은 합성 문장(실제 통화 아님).
const EXAMPLE = "서울중앙지검 수사관입니다. 고객님 명의 계좌가 범죄에 연루돼 안전계좌로 이체하셔야 합니다";
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function caption(page, text) {
  await page.evaluate((t) => {
    let el = document.getElementById("__demo_caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "__demo_caption";
      Object.assign(el.style, {
        position: "fixed", right: "20px", top: "20px", zIndex: 99999,
        background: "rgba(17,24,39,.88)", color: "#fff", padding: "12px 22px", borderRadius: "10px",
        font: "600 18px/1.45 sans-serif", maxWidth: "460px", textAlign: "left", boxShadow: "0 4px 16px rgba(0,0,0,.25)", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
}

async function center(loc) {
  await loc.first().waitFor();
  await loc.first().evaluate((el) => el.scrollIntoView({ block: "center", behavior: "smooth" }));
  await wait(700);
}

async function vwPost(p, body) {
  const res = await fetch(`${VW}${p}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json();
  if (!res.ok) throw new Error(`${p} ${res.status} ${JSON.stringify(data)}`);
  return data;
}

async function analyzeExample() {
  const res = await fetch(`${API}/api/v1/calls/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
    body: JSON.stringify({ transcript: EXAMPLE }),
  });
  const data = await res.json();
  if (!res.ok || !data.verification_prompt?.required) throw new Error(`analyze ${res.status} ${JSON.stringify(data)}`);
  return data;
}

function expect(ok, scene, result) {
  if (!ok) throw new Error(`${scene}: 기대와 다른 결과 ${JSON.stringify(result)}`);
}

async function submit(page, scope, code) {
  const box = scope.getByLabel("확인 코드 6자리");
  await box.fill("");
  await box.pressSequentially(code, { delay: 180 });
  await wait(600);
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/verification") && r.request().method() === "POST"),
    scope.getByRole("button", { name: "확인하기" }).click(),
  ]);
  return (await res.json());
}

const errors = [];
const browser = await chromium.launch({ args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: VIDEO_DIR, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
const log = (s) => console.log(new Date().toISOString().slice(11, 19), s);

try {
  // 1. 탐지
  await page.goto(`${URL_}/dashboard?demo=verify`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await caption(page, "① 기관사칭 의심 통화를 AI가 분석합니다 (모의 시연)");
  const section = page.getByRole("region", { name: "상대 신원 확인 (모의)" });
  await section.waitFor({ timeout: 60000 });
  await caption(page, "AI는 '의심'만 합니다 — 확정은 상대 신원확인으로");
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await wait(3500);
  await section.scrollIntoViewIfNeeded();
  await wait(2500);
  log("scene1 done");

  // 2. 정상 직원
  await caption(page, "② 진짜 은행 직원: 직원 휴대폰(모의)에서 확인 코드를 만듭니다");
  await wait(2000);
  await section.getByRole("button", { name: "확인 코드 만들기" }).click();
  await wait(2500);
  const code = (await section.locator("section[aria-live] p").nth(1).innerText()).replace(/\D/g, "");
  await center(section.locator("section[aria-live] p").nth(1));
  await wait(1500);
  await caption(page, `고객이 불러받은 코드 ${code}를 입력합니다`);
  const r1 = await submit(page, section, code);
  await center(section.getByText(/확인된 .* 직원입니다/));
  await caption(page, "✔ 확인된 직원입니다 — 안심하고 통화를 이어갑니다");
  await wait(4000);
  expect(r1.verified, "정상 직원", r1);
  log(`genuine: ${r1.reason}`);

  // 대시보드 표 배지
  await caption(page, "관제 대시보드의 해당 통화에도 '신원확인됨'이 붙습니다");
  await center(page.locator("table").first().getByText("신원확인됨"));
  await wait(4000);

  // 3. 사칭범 (새 통화 — 이전 직원 코드가 화면에 남지 않게 국민 화면 단독으로)
  const imp = await analyzeExample();
  await page.goto(`${URL_}/verify/citizen?call_id=${imp.call_id}`, { waitUntil: "networkidle" });
  await caption(page, "③ 사칭범: 진짜 코드가 없어 아무 숫자나 부릅니다");
  await wait(3000);
  const r2 = await submit(page, page, "000000");
  await center(page.getByText("숫자가 맞지 않습니다", { exact: false }));
  await caption(page, "1회차는 입력 실수일 수 있어 다시 입력하도록 안내합니다 (보호자 알림 없음)");
  await wait(4500);
  const r3 = await submit(page, page, "000001");
  await center(page.getByText("확인되지 않았습니다. 전화를 끊으세요"));
  await caption(page, "✖ 2회차 실패 — 전화를 끊으라고 안내하고 보호자에게 알립니다(모의)");
  await wait(5500);
  expect(r2.retry_allowed && !r2.guardian_notification, "사칭범 1회차", r2);
  expect(!r3.verified && !r3.retry_allowed && r3.guardian_notification, "사칭범 2회차", r3);
  log(`impersonator: ${r2.reason}/${r2.retry_allowed} -> ${r3.reason}/${!!r3.guardian_notification}`);

  // 4. 퇴사자 (자격증명 새로 발급 → 증명 → 폐기)
  const cred = await vwPost("/api/v1/credentials", { institution_name: "○○은행(모의)", staff_display_name: "최퇴사", role: "대출상담 직원" });
  const proof = await vwPost("/api/v1/proofs", { credential_id: cred.credential_id, purpose: "대출 상담 전화" });
  await vwPost(`/api/v1/credentials/${cred.credential_id}/revoke`);
  const an = await analyzeExample();
  await page.goto(`${URL_}/verify/citizen?call_id=${an.call_id}`, { waitUntil: "networkidle" });
  await caption(page, "④ 퇴사자: 퇴사 전에 받은 코드를 부르지만, 자격증명이 이미 폐기됐습니다");
  await wait(3000);
  const r4 = await submit(page, page, proof.code);
  await center(page.getByText("확인되지 않았습니다. 전화를 끊으세요"));
  await caption(page, "✖ 폐기된 자격증명 — 확인 불가");
  await wait(4500);
  expect(r4.reason === "credential_revoked", "퇴사자", r4);
  log(`resigned: ${r4.reason}`);

  // 5. 방문 QR
  await page.goto(`${URL_}/verify/staff`, { waitUntil: "networkidle" });
  await caption(page, "⑤ 방문 점검: 도시가스 직원(모의)이 현관에서 QR을 보여줍니다");
  await wait(2000);
  await page.getByRole("radio", { name: /□□도시가스\(모의\)/ }).check();
  await wait(800);
  await page.getByRole("combobox").selectOption("가스 점검 방문(모의)");
  await wait(800);
  await page.getByRole("button", { name: "확인 코드 만들기" }).click();
  await center(page.locator("svg").filter({ has: page.locator("title") }));
  const vcode = (await page.locator("section[aria-live] p").nth(1).innerText()).replace(/\D/g, "");
  await wait(4000);
  await page.goto(`${URL_}/verify/citizen?code=${vcode}`, { waitUntil: "networkidle" });
  await caption(page, "QR을 읽으면 코드가 미리 채워집니다 — 거주자가 직접 '확인하기'를 눌러야 검증합니다");
  await wait(4000);
  const [res5] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/verification") && r.request().method() === "POST"),
    page.getByRole("button", { name: "확인하기" }).click(),
  ]);
  const r5 = await res5.json();
  await center(page.getByText(/확인된 .* 직원입니다/));
  await caption(page, "✔ 확인된 □□도시가스(모의) 직원입니다");
  await wait(4500);
  expect(r5.verified, "방문", r5);
  log(`visit: ${r5.reason}`);
} finally {
  await ctx.close(); // 이때 영상 파일이 마무리된다
  await browser.close();
}

const webm = path.join(VIDEO_DIR, fs.readdirSync(VIDEO_DIR).find((f) => f.endsWith(".webm")));
try {
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-movflags", "+faststart", OUT]);
  console.log(`video -> ${OUT}`);
} catch {
  console.log(`ffmpeg 변환 실패 — 원본 webm: ${webm}`);
}
console.log(errors.length ? `console errors:\n${errors.join("\n")}` : "console errors: none");
