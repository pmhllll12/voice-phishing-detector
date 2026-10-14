"use client";

// 역방향 신원확인 POC — 직원용 화면(모의). 직원용 페이지(/verify/staff)와 관제 대시보드
// ("직원 휴대폰(모의)" 패널)가 함께 쓴다. 통화/방문 중인 기관 직원이 자기 자격증명을 골라
// 일회용 증명(6자리 코드)을 만들고, 그 코드를 국민에게 말로 불러준다(어디로도 전송하지 않음 —
// 버튼 이름을 "증명 보내기"에서 "확인 코드 만들기"로 바꾼 이유). 국민은 /verify/citizen에서
// 코드를 입력해 확인한다. 자격증명은 verify-worker가 기동 시 시드한 모의 기관 것들이다.
//
// 방문 시나리오: 거주자가 문을 열지 않고 확인해야 하므로 방문도 기본은 6자리를 문 너머·인터폰으로
// 불러주는 것이다. 같은 증명을 담은 QR(/verify/citizen?code=XXXXXX)은 접어 둔 보조 경로로,
// 공동현관 영상 인터폰처럼 화면 너머로 보여줄 수 있을 때만 쓴다. 시연에서는 휴대폰 기본 카메라로
// 읽어 국민용 화면을 연다(실제 구조에서는 정부 앱 안에서 읽어야 한다, lib/verify.ts
// citizenVerifyUrl 참고).

import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  PROOF_PURPOSES,
  citizenVerifyUrl,
  createProof,
  listStaffCredentials,
  type CreatedProof,
  type StaffCredential,
} from "@/lib/verify";

const DEFAULT_PURPOSE: string = PROOF_PURPOSES[0];
const CUSTOM_PURPOSE = "__custom__";

const textFieldStyle = {
  padding: "12px 14px",
  borderRadius: "8px",
  border: "1px solid var(--baseline)",
  background: "var(--surface-1)",
  color: "var(--text-primary)",
} as const;

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

export function StaffProofPanel() {
  const [credentials, setCredentials] = useState<StaffCredential[]>([]);
  const [selectedId, setSelectedId] = useState<string>("");
  // 선택지 중 하나이거나 CUSTOM_PURPOSE(직접 입력). 직접 입력한 문구는 customPurpose에 둔다.
  const [purposeChoice, setPurposeChoice] = useState<string>(DEFAULT_PURPOSE);
  const [customPurpose, setCustomPurpose] = useState("");
  const purpose = purposeChoice === CUSTOM_PURPOSE ? customPurpose : purposeChoice;
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
          코드는 어디로도 전송되지 않습니다. 화면에 나온 6자리를 고객에게 말로 불러주세요. 방문했다면 문을 열어
          달라고 하지 말고, 닫힌 문 너머나 인터폰으로 불러주세요.
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
        <select value={purposeChoice} onChange={(e) => setPurposeChoice(e.target.value)} style={textFieldStyle}>
          {PROOF_PURPOSES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
          <option value={CUSTOM_PURPOSE}>직접 입력</option>
        </select>
      </label>
      {purposeChoice === CUSTOM_PURPOSE && (
        <input
          aria-label="목적 직접 입력"
          placeholder="예: 전입 신고 확인 방문(모의)"
          value={customPurpose}
          onChange={(e) => setCustomPurpose(e.target.value)}
          maxLength={50}
          style={textFieldStyle}
        />
      )}

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
          <p style={{ margin: "4px 0 0", fontSize: "15px", color: "var(--text-secondary)" }}>
            방문 중이면 문이 닫힌 채로, 인터폰이나 문 너머로
          </p>
          <p
            data-testid="proof-code"
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
          {!expired && (
            <details style={{ marginTop: "16px", paddingTop: "16px", borderTop: "1px solid var(--border)" }}>
              <summary style={{ cursor: "pointer", fontWeight: 700, marginBottom: "10px" }}>
                QR로 보여주기 (영상 인터폰용)
              </summary>
              <div style={{ display: "inline-block", padding: "10px", background: "#ffffff", borderRadius: "8px" }}>
                <QRCodeSVG
                  value={citizenVerifyUrl(proof.code)}
                  size={176}
                  marginSize={1}
                  title={`확인 코드 ${proof.code} QR (모의)`}
                />
              </div>
              <p style={{ margin: "10px 0 0", fontSize: "15px", color: "var(--text-secondary)" }}>
                QR에는 위 6자리와 같은 확인 코드가 들어 있습니다. 공동현관 영상 인터폰처럼 화면 너머로 보여줄 수
                있을 때만 쓰세요. 모의 시연에서는 휴대폰 기본 카메라로 읽으면 국민용 화면이 열리고, 실제 구조에서는
                정부 앱 안에서만 읽습니다.
              </p>
            </details>
          )}
        </section>
      )}
    </div>
  );
}
