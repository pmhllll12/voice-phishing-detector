"use client";

// 역방향 신원확인 POC — 직원용 화면(모의). 통화/방문 중인 기관 직원이 자기 자격증명을 골라
// 일회용 증명(6자리 코드)을 만들고, 그 코드를 국민에게 말로 불러준다(어디로도 전송하지 않음 —
// 버튼 이름을 "증명 보내기"에서 "확인 코드 만들기"로 바꾼 이유). 국민은 /verify/citizen에서
// 코드를 입력해 확인한다. 자격증명은 verify-worker가 기동 시 시드한 모의 기관 것들이다.

import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { createProof, listStaffCredentials, type CreatedProof, type StaffCredential } from "@/lib/verify";

const DEFAULT_PURPOSE = "대출 상담 전화";

function useRemainingSeconds(expiresAt: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!expiresAt) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [expiresAt]);
  if (!expiresAt) return null;
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - now) / 1000));
}

function formatMinSec(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}분 ${String(s).padStart(2, "0")}초`;
}

export default function StaffVerifyPage() {
  const [credentials, setCredentials] = useState<StaffCredential[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  const [purpose, setPurpose] = useState(DEFAULT_PURPOSE);
  const [proof, setProof] = useState<CreatedProof | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remaining = useRemainingSeconds(proof?.expires_at ?? null);

  useEffect(() => {
    listStaffCredentials()
      .then((list) => {
        const active = list.filter((c) => !c.revoked);
        setCredentials(active);
        if (active.length > 0) setSelectedId(active[0].credential_id);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "자격증명 목록을 불러오지 못했습니다."));
  }, []);

  async function handleSend() {
    if (!selectedId || !purpose.trim()) return;
    setLoading(true);
    setError(null);
    try {
      setProof(await createProof(selectedId, purpose.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "증명을 만들지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }

  const expired = remaining === 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      <header>
        <p style={{ margin: 0, color: "var(--text-secondary)" }}>직원용 · 모의 시연</p>
        <h1 style={{ margin: "4px 0 0", fontSize: "30px" }}>고객에게 불러줄 확인 코드</h1>
        <p style={{ margin: "8px 0 0", color: "var(--text-secondary)" }}>
          코드는 어디로도 전송되지 않습니다. 화면에 나온 6자리를 통화 중인 고객에게 말로 불러주세요.
        </p>
      </header>

      <fieldset style={{ border: "1px solid var(--border)", borderRadius: "10px", padding: "16px", margin: 0 }}>
        <legend style={{ padding: "0 6px", fontWeight: 700 }}>1. 자격증명 선택</legend>
        {credentials.length === 0 && !error && <p style={{ margin: 0 }}>불러오는 중…</p>}
        {credentials.map((c) => (
          <label
            key={c.credential_id}
            style={{ display: "flex", gap: "12px", alignItems: "flex-start", padding: "8px 0", cursor: "pointer" }}
          >
            <input
              type="radio"
              name="credential"
              value={c.credential_id}
              checked={selectedId === c.credential_id}
              onChange={() => setSelectedId(c.credential_id)}
              style={{ width: "24px", height: "24px", marginTop: "4px" }}
            />
            <span>
              <strong>{c.institution_name}</strong> · {c.staff_display_name}
              <br />
              <span style={{ color: "var(--text-secondary)" }}>{c.role}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <span style={{ fontWeight: 700 }}>2. 통화/방문 목적</span>
        <input
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          maxLength={50}
          style={{
            padding: "12px 14px",
            borderRadius: "8px",
            border: "1px solid var(--baseline)",
            background: "var(--surface-1)",
            color: "var(--text-primary)",
          }}
        />
      </label>

      <button
        type="button"
        className="verify-primary-button"
        onClick={handleSend}
        disabled={loading || !selectedId || !purpose.trim()}
      >
        {loading ? "만드는 중…" : proof ? "새 확인 코드 만들기" : "확인 코드 만들기"}
      </button>

      {error && (
        <p role="alert" style={{ margin: 0, color: "var(--status-critical)" }}>
          {error}
        </p>
      )}

      {proof && remaining !== null && (
        <section
          aria-live="polite"
          style={{
            border: `2px solid ${expired ? "var(--baseline)" : "var(--series-1)"}`,
            borderRadius: "12px",
            padding: "20px",
            textAlign: "center",
            background: "var(--surface-1)",
          }}
        >
          <p style={{ margin: 0 }}>고객에게 이 코드를 불러주세요</p>
          <p
            style={{
              margin: "8px 0",
              fontSize: "48px",
              fontWeight: 800,
              letterSpacing: "0.2em",
              fontVariantNumeric: "tabular-nums",
              textDecoration: expired ? "line-through" : "none",
              color: expired ? "var(--text-muted)" : "var(--text-primary)",
            }}
          >
            {proof.code}
          </p>
          <p style={{ margin: 0, fontWeight: 700 }}>
            {expired ? "⏱ 만료됨 — 새 확인 코드를 만드세요" : `⏱ 남은 시간 ${formatMinSec(remaining)}`}
          </p>
          <p style={{ margin: "8px 0 0", color: "var(--text-secondary)" }}>목적: {proof.purpose} · 1회만 사용 가능</p>
        </section>
      )}
    </div>
  );
}
