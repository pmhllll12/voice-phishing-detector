// 역방향 신원확인 POC(모의) 시연 화면 캡처 — docs/poc-mobile-id.md와 공모전 기획서에 넣을
// 이미지를 docs/images/poc/에 만든다. 실제 모바일신분증과 연동하지 않는 모의 시제품 화면이다.
//
// Usage:
//   node capture_poc.mjs <frontend-url> [out-dir] [responses-dir]
//
// 전제: SKILL.md "Run (agent path)"대로 postgres + 백엔드 5개 + frontend가 떠 있어야 한다.
// verify-worker(VW, 기본 http://localhost:8400)는 퇴사자 시나리오의 자격증명 발급/폐기에 직접 쓴다.
//
// 장면(파일명 순서 = 시연 순서):
//   01-analyze.png                 대시보드에서 기관사칭 예시 분석 → 신원확인 안내
//   02-staff-code.png              대시보드 직원 휴대폰(모의)에서 확인 코드 생성
//   03-citizen-verified.png        고객 휴대폰(모의)에 코드 입력 → 확인됨
//   04-impersonator-retry.png      사칭범: 없는 코드 1회차 → 재입력 안내
//   05-impersonator-unverified.png 사칭범: 없는 코드 2회차 → 확인 불가 + 보호자 알림(모의)
//   06-resigned-unverified.png     퇴사자: 폐기된 자격증명의 코드 → 확인 불가
//   07-dashboard-records.png       대시보드 최근 탐지 현황: 세 통화에 붙은 신원확인 결과 배지
//   08-visit-staff-qr.png          방문: 직원 화면에서 □□도시가스(모의) + 방문 목적으로 코드·QR 생성
//   09-visit-citizen-prefilled.png 방문: QR 주소(/verify/citizen?code=…)를 열면 코드가 미리 채워짐
//   10-visit-verified.png          방문: 거주자가 "확인하기"를 눌러야 검증 → 확인됨
// QR 이미지 자체(visit-qr.png)도 responses-dir에 남긴다 — 내용이 위 주소와 같은지 디코더로 확인용.
// 사칭범/퇴사자 시나리오도 api로 같은 기관사칭 예시를 먼저 분석해 받은 call_id로 진행한다 —
// "AI가 의심 → 국민이 확인" 순서가 실제와 같고, 결과가 대시보드 표의 해당 통화에 붙는다.
// 각 장면의 api 응답 원문은 responses-dir에 JSON으로 남긴다(문서 3장에 옮길 때 쓴다).

import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";

const [, , url, outDirArg, responsesDirArg] = process.argv;
if (!url) {
  console.error("usage: node capture_poc.mjs <frontend-url> [out-dir] [responses-dir]");
  process.exit(1);
}
const VW = process.env.VW || "http://localhost:8400";
const API = process.env.API || "http://localhost:8000";
const API_KEY = process.env.API_KEY || "dev-handler-key";
// AnalyzeCallForm.tsx AUTHORITY_IMPERSONATION_EXAMPLE과 같은 합성 문장(실제 통화 아님).
const EXAMPLE = "서울중앙지검 수사관입니다. 고객님 명의 계좌가 범죄에 연루돼 안전계좌로 이체하셔야 합니다";
const outDir = outDirArg || path.resolve("../../../docs/images/poc");
const responsesDir = responsesDirArg || path.join(process.cwd(), "responses");
fs.mkdirSync(outDir, { recursive: true });
fs.mkdirSync(responsesDir, { recursive: true });

const saveJson = (name, data) => fs.writeFileSync(path.join(responsesDir, name), JSON.stringify(data, null, 2));
const shot = (name) => path.join(outDir, name);

async function vwPost(p, body) {
  const res = await fetch(`${VW}${p}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
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

// 국민 화면 1건: 코드 입력 → 확인하기 → api 응답을 기다려 돌려준다.
async function submitCitizenCode(page, scope, code) {
  await scope.getByLabel("확인 코드 6자리").fill(code);
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/verification") && r.request().method() === "POST"),
    scope.getByRole("button", { name: "확인하기" }).click(),
  ]);
  return { status: response.status(), body: await response.json() };
}

const consoleErrors = [];
const browser = await chromium.launch({ args: ["--no-sandbox"] });
try {
  // ── 01~03: 관제 대시보드 한 화면 ──────────────────────────────────────────────
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await desktop.newPage();
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

  await page.goto(`${url}/dashboard`, { waitUntil: "networkidle", timeout: 30000 });
  const [analyzeResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/api/v1/calls/analyze"), { timeout: 60000 }),
    page.getByRole("button", { name: "기관사칭 예시로 바로 분석" }).click(),
  ]);
  const analyzed = await analyzeResponse.json();
  saveJson("01-analyze.json", { status: analyzeResponse.status(), body: analyzed });
  if (!analyzed.verification_prompt?.required) throw new Error("verification_prompt.required가 true가 아님");

  const section = page.getByRole("region", { name: "상대 신원 확인 (모의)" });
  await section.waitFor({ timeout: 15000 });
  await section.locator('input[type="radio"]:checked').waitFor();
  // 분석 폼 + "상대 신원 확인 권장" 안내까지(직원/고객 패널은 02·03에서 따로 보여준다).
  await page.evaluate(() => window.scrollTo(0, 0));
  const promptBox = await section.locator("div").first().boundingBox();
  await page.screenshot({ path: shot("01-analyze.png"), clip: { x: 0, y: 0, width: 1440, height: promptBox.y + promptBox.height + 16 } });

  await page.getByRole("button", { name: "확인 코드 만들기" }).click();
  const codeText = await section.getByTestId("proof-code").innerText();
  const code = codeText.replace(/\D/g, "");
  await section.screenshot({ path: shot("02-staff-code.png") });

  const verified = await submitCitizenCode(page, section, code);
  saveJson("03-citizen-verified.json", { call_id: analyzed.call_id, code, ...verified });
  await section.getByText(/확인된 .* 직원입니다/).waitFor();
  await section.screenshot({ path: shot("03-citizen-verified.png") });
  await desktop.close();

  // ── 04~06: 국민용 단독 화면(휴대폰 크기) ─────────────────────────────────────
  const mobile = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
  const m = await mobile.newPage();
  m.on("console", (msg) => msg.type() === "error" && consoleErrors.push(msg.text()));
  m.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));

  const impersonatorCall = (await analyzeExample()).call_id;
  await m.goto(`${url}/verify/citizen?call_id=${impersonatorCall}`, { waitUntil: "networkidle" });
  const first = await submitCitizenCode(m, m, "000000");
  await m.getByText("숫자가 맞지 않습니다", { exact: false }).waitFor();
  await m.getByLabel("확인 코드 6자리").fill("000001");
  await m.screenshot({ path: shot("04-impersonator-retry.png"), fullPage: true });
  const second = await submitCitizenCode(m, m, "000001");
  await m.getByText("확인되지 않았습니다. 전화를 끊으세요").waitFor();
  await m.screenshot({ path: shot("05-impersonator-unverified.png"), fullPage: true });
  saveJson("04-05-impersonator.json", { call_id: impersonatorCall, first, second });

  // 퇴사자: 시드 자격증명(demo-bank-staff)은 폐기하지 않는다 — 새로 발급해서 폐기한다.
  const resigned = await vwPost("/api/v1/credentials", {
    institution_name: "○○은행(모의)",
    staff_display_name: "최퇴사",
    role: "대출상담 직원",
  });
  const resignedProof = await vwPost("/api/v1/proofs", { credential_id: resigned.credential_id, purpose: "대출 상담 전화" });
  const revoked = await vwPost(`/api/v1/credentials/${resigned.credential_id}/revoke`);
  const resignedCall = (await analyzeExample()).call_id;
  await m.goto(`${url}/verify/citizen?call_id=${resignedCall}`, { waitUntil: "networkidle" });
  const resignedResult = await submitCitizenCode(m, m, resignedProof.code);
  await m.getByText("확인되지 않았습니다. 전화를 끊으세요").waitFor();
  await m.screenshot({ path: shot("06-resigned-unverified.png"), fullPage: true });
  saveJson("06-resigned.json", { call_id: resignedCall, issued: resigned, proof: resignedProof, revoked, result: resignedResult });
  await mobile.close();

  // ── 07: 대시보드 표에 붙은 결과 배지(최신 3건 = 퇴사자, 사칭범, 정상 직원) ─────────
  const desktop2 = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const d = await desktop2.newPage();
  await d.goto(`${url}/dashboard`, { waitUntil: "networkidle" });
  const table = d.locator("table").first();
  await table.getByText("신원확인됨").first().waitFor({ timeout: 15000 });
  await table.scrollIntoViewIfNeeded();
  // boundingBox는 뷰포트 기준이라 스크롤 위치를 더해 전체 페이지 좌표로 바꾼다.
  const scrollY = await d.evaluate(() => window.scrollY);
  const head = await table.locator("thead").boundingBox();
  const third = await table.locator("tbody tr").nth(2).boundingBox();
  await d.screenshot({
    path: shot("07-dashboard-records.png"),
    fullPage: true,
    clip: { x: head.x, y: head.y + scrollY, width: head.width, height: third.y + third.height - head.y },
  });
  await desktop2.close();

  // ── 08~10: 방문 시나리오(QR) ─────────────────────────────────────────────────
  const visit = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
  const v = await visit.newPage();
  v.on("console", (msg) => msg.type() === "error" && consoleErrors.push(msg.text()));
  v.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
  await v.goto(`${url}/verify/staff`, { waitUntil: "networkidle" });
  await v.getByRole("radio", { name: /□□도시가스\(모의\)/ }).check();
  await v.getByRole("combobox").selectOption("가스 점검 방문(모의)");
  await v.getByRole("button", { name: "확인 코드 만들기" }).click();
  // QR은 영상 인터폰용 보조 경로라 접혀 있다 — 펼쳐서 찍는다.
  await v.getByText("QR로 보여주기").click();
  const qr = v.locator("svg").filter({ has: v.locator("title") }).first();
  await qr.waitFor();
  const visitCode = (await v.getByTestId("proof-code").innerText()).replace(/\D/g, "");
  await qr.screenshot({ path: path.join(responsesDir, "visit-qr.png") });
  await v.screenshot({ path: shot("08-visit-staff-qr.png"), fullPage: true });

  // QR에 담긴 주소를 그대로 연다(휴대폰 기본 카메라가 하는 일). 연 것만으로 검증 요청이 나가면 안 된다.
  let verificationRequests = 0;
  v.on("request", (r) => r.url().includes("/verification") && r.method() === "POST" && verificationRequests++);
  await v.goto(`${url}/verify/citizen?code=${visitCode}`, { waitUntil: "networkidle" });
  const prefilled = await v.getByLabel("확인 코드 6자리").inputValue();
  if (prefilled !== visitCode) throw new Error(`미리 채우기 실패: ${prefilled} != ${visitCode}`);
  if (verificationRequests !== 0) throw new Error("주소를 연 것만으로 검증 요청이 나갔음");
  const requestsBeforeClick = verificationRequests;
  await v.screenshot({ path: shot("09-visit-citizen-prefilled.png"), fullPage: true });
  const visitResult = await submitCitizenCode(v, v, visitCode);
  await v.getByText(/확인된 .* 직원입니다/).waitFor();
  await v.screenshot({ path: shot("10-visit-verified.png"), fullPage: true });
  saveJson("08-10-visit.json", {
    code: visitCode,
    qr_url_expected: `${url}/verify/citizen?code=${visitCode}`,
    requests_before_click: requestsBeforeClick,
    result: visitResult,
  });
  await visit.close();
} finally {
  await browser.close();
}

console.log(`screenshots -> ${outDir}`);
console.log(`responses   -> ${responsesDir}`);
console.log(consoleErrors.length ? `console errors:\n${consoleErrors.join("\n")}` : "console errors: none");
