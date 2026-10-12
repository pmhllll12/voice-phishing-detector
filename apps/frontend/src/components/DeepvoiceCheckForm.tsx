"use client";

import { useRef, useState } from "react";

import { ApiError, checkDeepvoice, type DeepvoiceVerdict } from "@/lib/api";

// F-06 대시보드 UI/UX 개선(2026-09-02, item 6): F-03(딥보이스/AI 합성음성 판별)을 위한
// 대시보드 진입점. AnalyzeCallForm(F-01/F-02/F-05, 통화 "내용"의 위험도 판정)과는
// 완전히 다른 질문에 답한다 — "이 음성이 사람 목소리인가, AI가 만든 것인가". 그래서
// 같은 폼에 섞지 않고 별도 섹션으로 둔다. WAV만 지원하는 이유는 lib/api.ts
// checkDeepvoice 상단 주석 참고 — 브라우저 마이크 녹음(webm/mp4/ogg)을 바로 쓸 수
// 없어서 파일 업로드 방식으로 구현했다.
export function DeepvoiceCheckForm() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<DeepvoiceVerdict | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleCheck() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setVerdict(null);
    try {
      const result = await checkDeepvoice(file);
      setVerdict(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "딥보이스 판별 요청에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  function verdictLabel(v: DeepvoiceVerdict): { text: string; color: string } {
    if (v.is_synthetic === null) return { text: "판단 보류 (신호 부족)", color: "var(--text-muted)" };
    return v.is_synthetic
      ? { text: "AI 합성 음성으로 의심됨", color: "var(--status-critical)" }
      : { text: "육성으로 판단됨", color: "var(--status-good)" };
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <p style={{ margin: 0, fontSize: "13px", color: "var(--text-muted)" }}>
        16-bit PCM WAV 파일만 지원합니다(마이크 녹음 파일은 형식이 달라 바로 쓸 수 없습니다 —
        F-05 &quot;음성으로 분석&quot;과는 별개 기능입니다).
      </p>
      <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
        <input
          ref={fileInputRef}
          type="file"
          accept="audio/wav,.wav"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setVerdict(null);
            setError(null);
          }}
          style={{ fontSize: "13px", color: "var(--text-secondary)" }}
        />
        <button
          type="button"
          onClick={handleCheck}
          disabled={!file || loading}
          style={{
            padding: "8px 16px",
            borderRadius: "6px",
            border: "none",
            background: "var(--series-1)",
            color: "#ffffff",
            fontSize: "14px",
            cursor: loading ? "default" : "pointer",
            opacity: !file || loading ? 0.6 : 1,
          }}
        >
          {loading ? "판별 중…" : "딥보이스 판별하기"}
        </button>
        {error && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{error}</span>}
      </div>

      {verdict && (
        <div
          style={{
            marginTop: "4px",
            padding: "12px 14px",
            borderRadius: "6px",
            border: "1px solid var(--gridline)",
            background: "var(--surface-1)",
            fontSize: "13px",
          }}
        >
          <div style={{ fontWeight: 600, color: verdictLabel(verdict).color, marginBottom: "4px" }}>
            {verdictLabel(verdict).text} (신뢰도 {Math.round(verdict.confidence * 100)}%)
          </div>
          <p style={{ margin: "0 0 6px", color: "var(--text-secondary)" }}>{verdict.explanation}</p>
          {verdict.indicators.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "16px", color: "var(--text-muted)" }}>
              {verdict.indicators.map((ind) => (
                <li key={ind.name} style={{ color: ind.triggered ? "var(--status-critical)" : "var(--text-muted)" }}>
                  {ind.description} {ind.triggered ? "— 감지됨" : "— 정상 범위"}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
