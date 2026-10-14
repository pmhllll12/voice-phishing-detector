"use client";

// 역방향 신원확인 POC — 국민용 화면(모의). 전화를 건 상대에게 받은 6자리 코드를 입력하면
// "확인됨(초록) / 확인 불가(빨강)" 두 가지 결과만 보여준다. 사유 코드(만료/폐기/재사용 등,
// N-04)는 api 응답과 통화 기록에는 남지만 이 화면에는 의도적으로 보여주지 않는다 — 국민이
// 판단할 것은 "끊을지 말지" 하나뿐이어야 한다.
//
// 고령층 기준: 본문 20px 이상, 결과 문구 32px 이상, 색만이 아니라 아이콘(✔/✖)과 문구로도
// 구분, 화면당 버튼 하나.
//
// 국민용 페이지(/verify/citizen)와 관제 대시보드(분석 결과 아래 "고객 휴대폰(모의)" 패널)가
// 이 컴포넌트를 함께 쓴다. callId로 넘긴 통화 기록에 검증 결과가 붙는다(apps/api
// CallVerificationService 참고).
//
// 방문 시나리오: 문을 연 채로 확인하면 의미가 없으므로 기본은 방문자가 문 너머·인터폰으로
// 6자리를 불러주는 방식이다(전화와 같은 입력). 단독 페이지에서는 "전화가 왔어요 / 누가
// 찾아왔어요"를 골라 문구를 바꾼다(allowSceneSwitch, ?scene=visit로도 시작 가능).
// QR은 보조 경로다 — 공동현관 영상 인터폰처럼 화면 너머로 보여줄 수 있을 때만 쓴다. 직원 화면의
// QR이 /verify/citizen?code=XXXXXX를 담고 있어서, 주소로 코드가 들어오면(initialCode) 입력칸에
// 미리 채운다. 확인 버튼은 사람이 직접 누른다 — 링크를 연 것만으로 검증되면 안 된다. 이 링크
// 방식은 시연 편의용이고, 실제 구조에서는 정부 앱 안에서 QR을 읽어야 한다(가짜 QR 링크 피싱
// 방지, docs/poc-mobile-id.md 참고).

import { useState, type FormEvent } from "react";

import { ApiError } from "@/lib/api";
import { verifyCallIdentity, type CallVerification } from "@/lib/verify";

// visitQr: 방문 + QR로 코드가 미리 채워진 경우. 결과 문구는 visit과 같다.
type Scene = "call" | "visit" | "visitQr";

const VISIT_OK_CAUTION =
  "직원이 맞아도 송금, 비밀번호, 앱 설치를 요구하면 돌려보내세요. 방문 내용이 위 목적과 다를 때도 돌려보내세요.";

// 전화/방문에 따라 달라지는 문구만 모았다. 결과는 어느 쪽이든 확인됨/확인 불가 두 가지다.
const SCENE_TEXT: Record<
  Scene,
  {
    title: string;
    step1: React.ReactNode;
    step2: string;
    retry: string;
    warning: string;
    failHeadline: string;
    okCaution: string;
  }
> = {
  call: {
    title: "전화한 사람이 진짜 직원인지 확인하기",
    step1: (
      <>
        <strong>1.</strong> 전화한 사람에게 <strong>&ldquo;확인 코드를 불러 주세요&rdquo;</strong>라고 말하세요.
      </>
    ),
    step2: "불러 준 확인 코드 6자리를 입력하세요.",
    retry: "숫자가 맞지 않습니다. 상대방에게 확인 코드를 한 번 더 불러 달라고 하세요. 한 번 더 맞지 않으면 확인 불가로 처리됩니다.",
    warning: "확인 코드를 못 대거나 둘러대면 사칭일 수 있습니다. 전화를 끊으세요.",
    failHeadline: "확인되지 않았습니다. 전화를 끊으세요",
    okCaution: "직원이 맞아도 송금, 비밀번호, 앱 설치를 요구하면 전화를 끊으세요. 통화 내용이 위 목적과 다를 때도 끊으세요.",
  },
  visit: {
    title: "찾아온 사람이 진짜 직원인지 확인하기",
    step1: (
      <>
        <strong>1.</strong> <strong>문을 열지 말고</strong>, 인터폰이나 문 너머로{" "}
        <strong>&ldquo;확인 코드를 불러 주세요&rdquo;</strong>라고 말하세요.
      </>
    ),
    step2: "불러 준 확인 코드 6자리를 입력하세요.",
    retry: "숫자가 맞지 않습니다. 문을 연 채로 기다리지 말고, 확인 코드를 한 번 더 불러 달라고 하세요. 한 번 더 맞지 않으면 확인 불가로 처리됩니다.",
    warning: "확인 코드를 못 대거나 둘러대면 사칭일 수 있습니다. 문을 열어 주지 마세요.",
    failHeadline: "확인되지 않았습니다. 문을 열어 주지 마세요",
    okCaution: VISIT_OK_CAUTION,
  },
  visitQr: {
    title: "찾아온 사람이 진짜 직원인지 확인하기",
    step1: (
      <>
        <strong>1.</strong> 영상 인터폰으로 보여준 <strong>QR로 확인 코드가 입력</strong>되어 있습니다. 상대방
        화면의 6자리와 같은지 확인하세요.
      </>
    ),
    step2: "숫자가 같으면 아래 \"확인하기\"를 누르세요. 다르면 상대방에게 6자리를 불러 달라고 해서 직접 입력하세요.",
    retry: "숫자가 맞지 않습니다. 확인 코드를 한 번 더 불러 달라고 하세요. 한 번 더 맞지 않으면 확인 불가로 처리됩니다.",
    warning: "QR이나 확인 코드를 못 대거나 둘러대면 사칭일 수 있습니다. 문을 열어 주지 마세요.",
    failHeadline: "확인되지 않았습니다. 문을 열어 주지 마세요",
    okCaution: VISIT_OK_CAUTION,
  },
};

const resultHeadlineStyle = { margin: "8px 0 16px", fontSize: "34px", lineHeight: 1.35, fontWeight: 800 } as const;

function ResultPanel({
  tone,
  icon,
  label,
  minHeight,
  children,
}: {
  tone: "ok" | "fail";
  icon: string;
  label: string;
  minHeight: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-live="assertive"
      style={{
        background: tone === "ok" ? "var(--verify-ok-bg)" : "var(--verify-fail-bg)",
        color: "var(--verify-on-result)",
        borderRadius: "16px",
        padding: "28px 20px",
        minHeight,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
      }}
    >
      <p style={{ margin: 0, fontSize: "26px", fontWeight: 700 }}>
        <span aria-hidden="true" style={{ fontSize: "56px", lineHeight: 1, display: "block", marginBottom: "8px" }}>
          {icon}
        </span>
        {label}
      </p>
      {children}
    </section>
  );
}

function VerifiedResult({ result, minHeight, scene }: { result: CallVerification; minHeight: string; scene: Scene }) {
  return (
    <ResultPanel tone="ok" icon="✔" label="확인됨" minHeight={minHeight}>
      <p style={resultHeadlineStyle}>확인된 {result.institution_name} 직원입니다</p>
      <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px" }}>
        <dt style={{ fontWeight: 700 }}>기관</dt>
        <dd style={{ margin: 0 }}>{result.institution_name}</dd>
        <dt style={{ fontWeight: 700 }}>성명</dt>
        <dd style={{ margin: 0 }}>{result.staff_display_name}</dd>
        <dt style={{ fontWeight: 700 }}>목적</dt>
        <dd style={{ margin: 0 }}>{result.purpose}</dd>
      </dl>
      {/* "확인됨"은 "이 사람이 그 기관 직원"까지만 보증한다 — "시키는 대로 해도 된다"로 읽히지
          않도록, 진짜 직원이라도 끊어야 하는 요구를 결과 화면 안에 함께 적는다. */}
      <p
        style={{
          margin: "20px 0 0",
          padding: "12px 14px",
          borderRadius: "10px",
          background: "rgba(0, 0, 0, 0.22)",
          fontWeight: 700,
        }}
      >
        <span aria-hidden="true">⚠ </span>
        {SCENE_TEXT[scene].okCaution}
      </p>
    </ResultPanel>
  );
}

function UnverifiedResult({ result, minHeight, scene }: { result: CallVerification; minHeight: string; scene: Scene }) {
  return (
    <ResultPanel tone="fail" icon="✖" label="확인 불가" minHeight={minHeight}>
      <p style={resultHeadlineStyle}>{SCENE_TEXT[scene].failHeadline}</p>
      <p style={{ margin: 0 }}>돈을 보내거나 앱을 설치하지 마세요.</p>
      <p style={{ margin: "8px 0 0" }}>궁금하면 그 기관의 대표번호로 직접 전화해 확인하세요.</p>
      {result.guardian_notification && (
        <p style={{ margin: "16px 0 0", fontWeight: 700 }}>
          <span aria-hidden="true">📨 </span>보호자에게 알렸습니다(모의)
        </p>
      )}
    </ResultPanel>
  );
}

// resultMinHeight: 단독 페이지에서는 결과 화면이 휴대폰 화면을 가득 채우게(55vh), 대시보드
// 안에 넣을 때는 패널 높이에 맞게 줄여서 쓴다. onVerified: 결과가 나오면 대시보드가 목록을
// 바로 다시 불러 신원확인 배지를 갱신하도록 알린다(10초 자동 갱신을 기다리지 않게).
export function CitizenVerifyPanel({
  callId,
  resultMinHeight = "55vh",
  onVerified,
  initialCode,
  initialScene = "call",
  allowSceneSwitch = false,
}: {
  callId: string;
  resultMinHeight?: string;
  onVerified?: () => void;
  initialCode?: string;
  initialScene?: "call" | "visit";
  // 단독 페이지에서만 켠다. 대시보드는 통화 기록에 붙는 화면이라 전화 상황으로 고정한다.
  allowSceneSwitch?: boolean;
}) {
  const prefilled = (initialCode ?? "").replace(/\D/g, "").slice(0, 6);
  const [baseScene, setBaseScene] = useState<"call" | "visit">(prefilled ? "visit" : initialScene);
  const scene: Scene = prefilled ? "visitQr" : baseScene;
  const [code, setCode] = useState(prefilled);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CallVerification | null>(null);
  const [failed, setFailed] = useState(false);
  // 입력 실수 재시도: 첫 번째 "없는 코드"는 결과 화면으로 넘어가지 않고 입력 화면에 머물며
  // 다시 불러 달라고 안내한다. 빨강(확인 불가)과 섞이지 않도록 별도 상태로 둔다.
  const [retryNotice, setRetryNotice] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (code.length !== 6) return;
    setLoading(true);
    setFailed(false);
    try {
      // 429(rate_limited)도 verified=false 결과로 돌아와 아래 확인 불가 화면으로 간다(lib/verify.ts).
      const verification = await verifyCallIdentity(callId, code);
      onVerified?.();
      if (verification.retry_allowed) {
        setCode("");
        setRetryNotice(true);
      } else {
        setRetryNotice(false);
        setResult(verification);
      }
    } catch (err) {
      // 서버 오류 상세(실행 명령 등 개발자용 안내)는 국민 화면에 보여주지 않고 콘솔에만 남긴다.
      console.error("신원확인 요청 실패:", err instanceof ApiError ? err.message : err);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setCode("");
    setResult(null);
    setFailed(false);
    setRetryNotice(false);
  }

  if (result) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        {result.verified ? (
          <VerifiedResult result={result} minHeight={resultMinHeight} scene={scene} />
        ) : (
          <UnverifiedResult result={result} minHeight={resultMinHeight} scene={scene} />
        )}
        <button type="button" className="verify-primary-button" onClick={reset}>
          처음으로
        </button>
      </div>
    );
  }

  // 시스템 오류(서버 꺼짐 등)는 "확인 불가(빨강)"와 섞지 않는다 — 검증 자체를 못 한 것이지
  // 상대가 사칭범으로 판정된 게 아니다. 대신 확인 전까지 송금하지 말라는 안내는 똑같이 준다.
  if (failed) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        <section
          role="alert"
          style={{ border: "2px solid var(--baseline)", borderRadius: "16px", padding: "24px 20px" }}
        >
          <p style={{ margin: 0, fontSize: "32px", fontWeight: 800 }}>
            <span aria-hidden="true">⚠ </span>지금은 확인할 수 없습니다
          </p>
          <p style={{ margin: "12px 0 0" }}>잠시 후 다시 시도하세요. 확인되기 전에는 돈을 보내지 마세요.</p>
        </section>
        <button type="button" className="verify-primary-button" onClick={reset}>
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      <header>
        <p style={{ margin: 0, color: "var(--text-secondary)" }}>국민용 · 모의 시연</p>
        <h1 style={{ margin: "4px 0 0", fontSize: "32px", lineHeight: 1.35 }}>{SCENE_TEXT[scene].title}</h1>
      </header>
      {allowSceneSwitch && !prefilled && (
        <div role="group" aria-label="상황 고르기" style={{ display: "flex", gap: "10px" }}>
          {(
            [
              ["call", "📞 전화가 왔어요"],
              ["visit", "🚪 누가 찾아왔어요"],
            ] as const
          ).map(([value, label]) => {
            const active = baseScene === value;
            return (
              <button
                key={value}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setBaseScene(value);
                  setRetryNotice(false);
                }}
                style={{
                  flex: 1,
                  padding: "14px 10px",
                  fontSize: "20px",
                  fontWeight: 700,
                  borderRadius: "10px",
                  cursor: "pointer",
                  border: `2px solid ${active ? "var(--series-1)" : "var(--baseline)"}`,
                  background: "var(--surface-1)",
                  color: active ? "var(--text-primary)" : "var(--text-secondary)",
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
      <p style={{ margin: 0 }}>{SCENE_TEXT[scene].step1}</p>
      <label style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        <span>
          <strong>2.</strong> {SCENE_TEXT[scene].step2}
        </span>
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
          inputMode="numeric"
          autoComplete="one-time-code"
          placeholder="000000"
          aria-label="확인 코드 6자리"
          style={{
            fontSize: "40px",
            letterSpacing: "0.3em",
            textAlign: "center",
            padding: "14px",
            borderRadius: "10px",
            border: "2px solid var(--baseline)",
            background: "var(--surface-1)",
            color: "var(--text-primary)",
            fontVariantNumeric: "tabular-nums",
          }}
        />
      </label>
      {retryNotice ? (
        <p
          role="alert"
          style={{
            margin: 0,
            padding: "12px 14px",
            borderRadius: "10px",
            border: "2px solid var(--status-warning)",
            background: "var(--status-warning-bg)",
            color: "var(--text-primary)",
            fontWeight: 700,
          }}
        >
          <span aria-hidden="true">⚠ </span>
          {SCENE_TEXT[scene].retry}
        </p>
      ) : (
        <p style={{ margin: 0, color: "var(--status-critical)", fontWeight: 700 }}>
          <span aria-hidden="true">⚠ </span>
          {SCENE_TEXT[scene].warning}
        </p>
      )}
      <button type="submit" className="verify-primary-button" disabled={loading || code.length !== 6}>
        {loading ? "확인 중…" : "확인하기"}
      </button>
    </form>
  );
}
