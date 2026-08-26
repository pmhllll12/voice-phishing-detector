// Playwright driver for the F-06 dashboard smoke test.
//
// Usage:
//   node driver.mjs <frontend-url> [call-text] [screenshot-dir]
//
// Example:
//   node driver.mjs http://localhost:3001 "검찰청 수사관인데 계좌가 범죄에 연루돼서 지금 즉시 안전계좌로 이체해야 한다고 전화왔어"
//
// Fills the "통화 분석해보기" textarea, submits, and screenshots before/after.
// Prints the rendered page text and any browser console errors to stdout.

import { chromium } from "playwright";
import path from "node:path";

const [, , url, callText, screenshotDirArg] = process.argv;

if (!url) {
  console.error("usage: node driver.mjs <frontend-url> [call-text] [screenshot-dir]");
  process.exit(1);
}

const text =
  callText ||
  "안녕하세요 검찰청 수사관입니다. 당신 계좌가 범죄에 연루되어 안전계좌로 즉시 이체하셔야 합니다.";
const screenshotDir = screenshotDirArg || path.join(process.cwd(), "screenshots");

// apps/api는 감사증적을 프로세스 메모리에만 쌓는다(postgres 미도입, README "F-06 관제
// 대시보드 로컬 실행" 참고) — 즉 이 드라이버를 여러 번 실행해도 이전 실행의 데이터가 그대로
// 남아있다. 그래서 "고위험 텍스트가 보이는지"가 아니라 "총 분석 건수 숫자가 증가했는지"로
// 판정해야 한다 — 안 그러면 이전 실행의 잔여 데이터를 새 결과로 착각하고 새로고침 주기(아래
// 참고)를 기다리지 않은 채 화면을 찍어버린다(실제로 겪은 문제).
async function getTotalCount(page) {
  const valueLocator = page
    .getByText("총 분석 건수", { exact: true })
    .locator("xpath=following-sibling::div[1]");
  const raw = await valueLocator.innerText();
  const n = parseInt(raw.replace(/[^0-9]/g, ""), 10);
  return Number.isNaN(n) ? 0 : n;
}

const browser = await chromium.launch({ args: ["--no-sandbox"] });
try {
  const page = await (await browser.newContext()).newPage();
  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push("pageerror: " + err.message));

  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.screenshot({ path: path.join(screenshotDir, "01-initial.png"), fullPage: true });

  const countBefore = await getTotalCount(page);

  const textarea = page.locator("textarea").first();
  await textarea.waitFor({ timeout: 10000 });
  await textarea.fill(text);

  const submitBtn = page.getByRole("button", { name: /분석/ }).first();
  await submitBtn.click();

  // F-01/F-02 판정은 Ollama 로컬 LLM 호출을 거친다 — 콜드 스타트면 수 초 걸릴 수 있고
  // (README "GPU 자원 사용" 참고), 대시보드 자체도 10초마다만 자동 갱신되므로 넉넉히 기다린다.
  const deadline = Date.now() + 25000;
  let countAfter = countBefore;
  while (Date.now() < deadline && countAfter <= countBefore) {
    await page.waitForTimeout(1000);
    countAfter = await getTotalCount(page);
  }
  if (countAfter <= countBefore) {
    console.error(`WARNING: 총 분석 건수가 늘지 않았습니다 (${countBefore} -> ${countAfter}) — 분석 요청이 실패했을 수 있습니다.`);
  }
  await page.screenshot({ path: path.join(screenshotDir, "02-after-submit.png"), fullPage: true });

  console.log("--- BODY TEXT ---");
  console.log((await page.locator("body").innerText()).slice(0, 3000));
  console.log("--- CONSOLE ERRORS ---");
  console.log(consoleErrors.length ? consoleErrors.join("\n") : "(none)");
} finally {
  await browser.close();
}
