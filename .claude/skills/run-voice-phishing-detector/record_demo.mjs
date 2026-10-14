// 역방향 신원확인 POC(모의) 시연 영상 녹화 — capture_poc.mjs와 같은 시연 경로를 사람이 보는
// 속도로 한 창(1440x900)에서 진행하며 녹화하고, 장면마다 화면 아래쪽 가운데에 설명 자막을 붙인다.
// 앞뒤에 제목/요약 카드를 넣는다.
// 실제 모바일신분증과 연동하지 않는 모의 시제품 화면이다.
//
// Usage:
//   node record_demo.mjs <frontend-url> [out.mp4]
//
// 전제: SKILL.md "Run (agent path)"대로 postgres + 백엔드 5개 + frontend가 떠 있어야 한다.
// mp4 변환에 ffmpeg가 필요하다(없으면 Playwright 원본 .webm만 남긴다).
//
// 장면(약 1분 45초):
//   제목 카드     아이디어명 + 모의 시연 고지
//   ① 탐지        /dashboard?demo=verify 자동 분석 → 대시보드 표의 AI 판정(위험도·기관사칭) 강조
//                 → 상대 신원 확인 권장
//   ② 정상 직원   대시보드 직원 휴대폰(모의)에서 코드 생성 → 고객 휴대폰(모의)에 입력 → 확인됨,
//                 대시보드 표의 "신원확인됨" 배지
//   ③ 사칭범      새 통화의 국민 화면에서 000000(재입력 안내) → 000001(확인 불가 + 보호자 알림(모의))
//                 — 대시보드 화면에 앞 장면의 진짜 코드가 남아 있으면 헷갈려서 국민 화면 단독으로 한다
//   ④ 퇴사자      새 자격증명 발급 → 코드 생성 → 폐기 후 그 코드 입력 → 확인 불가
//                 (시드 demo-bank-staff는 폐기하지 않는다)
//   ⑤ 방문        □□도시가스(모의) 방문 코드 → 문 너머로 불러줌 → 국민 화면 "누가 찾아왔어요"에
//                 입력 → 확인됨 (QR은 영상 인터폰용 보조 경로라 녹화에서 열지 않음)
//   요약 카드     "증명하지 못하면 끊는다"
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
        // 아래쪽 가운데: 화면 내용(왼쪽 정렬, 가운데로 스크롤)과 하단 모의 고지 문구를 가리지 않는 위치.
        position: "fixed", left: "50%", bottom: "64px", transform: "translateX(-50%)", zIndex: 99999,
        background: "rgba(17,24,39,.9)", color: "#fff", padding: "14px 28px", borderRadius: "12px",
        font: "600 22px/1.45 sans-serif", maxWidth: "1000px", width: "max-content", textAlign: "center",
        boxShadow: "0 4px 16px rgba(0,0,0,.25)", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
}

// 화면 전체를 덮는 제목/요약 카드. lines[0]은 크게, 나머지는 작게.
async function card(page, lines, ms) {
  await page.evaluate((ls) => {
    const el = document.createElement("div");
    el.id = "__demo_card";
    Object.assign(el.style, {
      position: "fixed", inset: "0", zIndex: 100000, background: "#1f3864", color: "#fff",
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "18px",
      font: "500 24px/1.5 sans-serif", textAlign: "center", padding: "0 80px",
    });
    ls.forEach((t, i) => {
      const p = document.createElement("div");
      p.textContent = t;
      if (i === 0) Object.assign(p.style, { font: "700 44px/1.35 sans-serif", marginBottom: "12px" });
      if (i === ls.length - 1) Object.assign(p.style, { fontSize: "18px", opacity: ".75", marginTop: "24px" });
      el.appendChild(p);
    });
    document.getElementById("__demo_caption")?.remove();
    document.body.appendChild(el);
  }, lines);
  await wait(ms);
  await page.evaluate(() => document.getElementById("__demo_card")?.remove());
}

async function highlight(loc, on = true) {
  await loc.evaluate((el, v) => {
    el.style.outline = v ? "4px solid #f59e0b" : "";
    el.style.outlineOffset = v ? "2px" : "";
  }, on);
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
// LLM 예열: 모델이 메모리에 없으면 첫 분석이 20초 넘게 걸려 녹화 첫 장면이 길어진다.
// 녹화(컨텍스트 생성) 전에 한 번 분석해 둔다. 이 분석도 감사 기록에 한 건 남는다.
await analyzeExample();
const browser = await chromium.launch({ args: ["--no-sandbox"] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: VIDEO_DIR, size: { width: 1440, height: 900 } } });
const page = await ctx.newPage();
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
const log = (s) => console.log(new Date().toISOString().slice(11, 19), s);

try {
  // 0. 제목 카드
  await page.setContent("<html><body style='margin:0;background:#1f3864'></body></html>");
  await card(page, [
    "먼저 증명하는 전화",
    "모바일신분증 기반 역방향 신원확인 서비스",
    "기관 직원이 먼저 소속을 증명하고, 국민은 \"확인됨 / 확인 불가\"만 봅니다",
    "시제품 시연 — 실제 모바일신분증·기관 시스템과 연동하지 않는 모의 화면입니다",
  ], 6500); // 녹화 시작 지연으로 영상에는 1초쯤 짧게 남는다

  // 1. 탐지 — 자막은 페이지가 뜨자마자 띄운다(분석 대기 시간이 자막 없이 지나가지 않게).
  const analyzed = page.waitForResponse((r) => r.url().includes("/calls/analyze") && r.request().method() === "POST", { timeout: 90000 });
  await page.goto(`${URL_}/dashboard?demo=verify`, { waitUntil: "domcontentloaded" });
  await caption(page, "① 기관사칭 의심 통화(합성 문장)를 AI가 분석합니다");
  const a0 = await (await analyzed).json();
  const section = page.getByRole("region", { name: "상대 신원 확인 (모의)" });
  await section.waitFor({ timeout: 60000 });
  const labels = (a0.detected_patterns || []).map((d) => d.category_label).join("·") || "의심 패턴";
  // 대시보드 표 맨 윗줄 = 방금 분석한 통화(최신순). 표 갱신을 기다린 뒤 강조한다.
  const row = page.locator("table").first().locator("tbody tr").first();
  await row.filter({ hasText: `(${a0.risk_score})` }).waitFor({ timeout: 15000 }).catch(() => {});
  await center(row);
  await highlight(row);
  await caption(page, `AI 판정: 위험도 ${a0.risk_score}점 · ${labels} 탐지 — 하지만 "진짜 직원인지"는 AI가 확정할 수 없습니다`);
  await wait(5500);
  await highlight(row, false);
  await center(section);
  await caption(page, "그래서 상대에게 신원 증명을 요청하라고 안내합니다 — 확정은 서명 검증으로");
  await wait(4000);
  log(`scene1 done: risk=${a0.risk_score} ${labels}`);

  // 2. 정상 직원
  await caption(page, "② 진짜 은행 직원: 직원 휴대폰(모의)에서 확인 코드를 만듭니다");
  await wait(2000);
  await section.getByRole("button", { name: "확인 코드 만들기" }).click();
  await wait(2500);
  const code = (await section.getByTestId("proof-code").innerText()).replace(/\D/g, "");
  await center(section.getByTestId("proof-code"));
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

  // 5. 방문 — 문을 연 채로 확인하면 의미가 없으므로 6자리를 문 너머·인터폰으로 불러주는 게 기본.
  //    QR은 직원 화면에서 접어 둔 보조 경로(영상 인터폰용)라 녹화에서는 열지 않는다.
  await page.goto(`${URL_}/verify/staff`, { waitUntil: "networkidle" });
  await caption(page, "⑤ 방문 점검: 도시가스 직원(모의)이 현관 앞에 왔습니다 — 문은 닫혀 있습니다");
  await wait(2500);
  await page.getByRole("radio", { name: /□□도시가스\(모의\)/ }).check();
  await wait(800);
  await page.getByRole("combobox").selectOption("가스 점검 방문(모의)");
  await wait(800);
  await page.getByRole("button", { name: "확인 코드 만들기" }).click();
  const codeBox = page.locator("section[aria-live]");
  await center(codeBox);
  const vcode = (await codeBox.getByTestId("proof-code").innerText()).replace(/\D/g, "");
  expect(vcode.length === 6, "방문 코드", { vcode });
  await caption(page, "직원은 문을 열어 달라고 하지 않고, 인터폰으로 6자리를 불러줍니다");
  await wait(4000);
  await page.goto(`${URL_}/verify/citizen`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /누가 찾아왔어요/ }).click();
  await caption(page, "거주자는 문을 닫은 채로, 정부 앱(모의)에 들은 코드를 입력합니다");
  await wait(3500);
  const r5 = await submit(page, page, vcode);
  await center(page.getByText(/확인된 .* 직원입니다/));
  await caption(page, "✔ 확인된 □□도시가스(모의) 직원 — 확인된 뒤에야 문을 엽니다");
  await wait(4500);
  expect(r5.verified, "방문", r5);
  log(`visit: ${r5.reason}`);

  // 요약 카드
  await card(page, [
    "증명하지 못하면 끊는다",
    "정상 직원 → 확인됨   ·   사칭범 → 확인 불가   ·   퇴사자 → 확인 불가   ·   방문(문 너머 코드) → 확인됨",
    "AI는 의심하고, 모바일신분증의 서명 검증이 확정합니다",
    "모의 시연 — 기관·서명 키·보호자 알림은 모두 가상입니다",
  ], 6000);
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
