"use client";

// 역방향 신원확인 POC — 국민용 화면(모의). 전화를 건 상대에게 받은 6자리 코드를 입력하면
// "확인됨(초록) / 확인 불가(빨강)" 두 가지 결과만 보여준다. 사유 코드(만료/폐기/재사용 등,
// N-04)는 api 응답과 통화 기록에는 남지만 이 화면에는 의도적으로 보여주지 않는다 — 국민이
// 판단할 것은 "끊을지 말지" 하나뿐이어야 한다.
//
// 고령층 기준: 본문 20px 이상, 결과 문구 32px 이상, 색만이 아니라 아이콘(✔/✖)과 문구로도
// 구분, 화면당 버튼 하나.
//
// call_id 쿼리(대시보드의 "상대 신원 확인" 링크가 붙여줌)가 있으면 그 통화 기록에 결과를
// 붙이고, 없으면 STANDALONE_CALL_ID로 기록한다(apps/api CallVerificationService 참고).

import { Suspense, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";

import { ApiError } from "@/lib/api";
import { STANDALONE_CALL_ID, verifyCallIdentity, type CallVerification } from "@/lib/verify";

const resultHeadlineStyle = { margin: "8px 0 16px", fontSize: "34px", lineHeight: 1.35, fontWeight: 800 } as const;

function ResultPanel({
  tone,
  icon,
  label,
  children,
}: {
  tone: "ok" | "fail";
  icon: string;
  label: string;
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
        minHeight: "55vh",
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

function VerifiedResult({ result }: { result: CallVerification }) {
  return (
    <ResultPanel tone="ok" icon="✔" label="확인됨">
      <p style={resultHeadlineStyle}>확인된 {result.institution_name} 직원입니다</p>
      <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "6px 16px" }}>
        <dt style={{ fontWeight: 700 }}>기관</dt>
        <dd style={{ margin: 0 }}>{result.institution_name}</dd>
        <dt style={{ fontWeight: 700 }}>성명</dt>
        <dd style={{ margin: 0 }}>{result.staff_display_name}</dd>
        <dt style={{ fontWeight: 700 }}>목적</dt>
        <dd style={{ margin: 0 }}>{result.purpose}</dd>
      </dl>
    </ResultPanel>
  );
}

function UnverifiedResult({ result }: { result: CallVerification }) {
  return (
    <ResultPanel tone="fail" icon="✖" label="확인 불가">
      <p style={resultHeadlineStyle}>확인되지 않았습니다. 전화를 끊으세요</p>
      <p style={{ margin: 0 }}>돈을 보내거나 앱을 설치하지 마세요.</p>
      {result.guardian_notification && (
        <p style={{ margin: "16px 0 0", fontWeight: 700 }}>
          <span aria-hidden="true">📨 </span>보호자에게 알렸습니다(모의)
        </p>
      )}
    </ResultPanel>
  );
}

function CitizenVerify() {
  const searchParams = useSearchParams();
  const callId = searchParams.get("call_id") || STANDALONE_CALL_ID;

  const [code, setCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CallVerification | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (code.length !== 6) return;
    setLoading(true);
    setError(null);
    try {
      setResult(await verifyCallIdentity(callId, code));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "확인 요청에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setCode("");
    setResult(null);
    setError(null);
  }

  if (result) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        {result.verified ? <VerifiedResult result={result} /> : <UnverifiedResult result={result} />}
        <button type="button" className="verify-primary-button" onClick={reset}>
          처음으로
        </button>
      </div>
    );
  }

  // 시스템 오류(서버 꺼짐 등)는 "확인 불가(빨강)"와 섞지 않는다 — 검증 자체를 못 한 것이지
  // 상대가 사칭범으로 판정된 게 아니다. 대신 확인 전까지 송금하지 말라는 안내는 똑같이 준다.
  if (error) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        <section
          role="alert"
          style={{ border: "2px solid var(--baseline)", borderRadius: "16px", padding: "24px 20px" }}
        >
          <p style={{ margin: 0, fontSize: "32px", fontWeight: 800 }}>
            <span aria-hidden="true">⚠ </span>지금은 확인할 수 없습니다
          </p>
          <p style={{ margin: "12px 0 0" }}>확인되기 전에는 돈을 보내지 마세요.</p>
          <p style={{ margin: "12px 0 0", color: "var(--text-secondary)", wordBreak: "break-all" }}>{error}</p>
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
        <h1 style={{ margin: "4px 0 0", fontSize: "32px", lineHeight: 1.35 }}>전화한 사람이 진짜 직원인지 확인하기</h1>
      </header>
      <label style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        <span>상대방에게 받은 숫자 6자리를 입력하세요</span>
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
      <button type="submit" className="verify-primary-button" disabled={loading || code.length !== 6}>
        {loading ? "확인 중…" : "확인하기"}
      </button>
    </form>
  );
}

export default function CitizenVerifyPage() {
  // useSearchParams는 정적 빌드 시 Suspense 경계가 필요하다(Next.js 14).
  return (
    <Suspense fallback={null}>
      <CitizenVerify />
    </Suspense>
  );
}
