"use client";

import { useState, type FormEvent } from "react";

import { analyzeCall, ApiError } from "@/lib/api";

export function AnalyzeCallForm({ onAnalyzed }: { onAnalyzed: () => void }) {
  const [transcript, setTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = transcript.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    try {
      await analyzeCall(trimmed);
      setTranscript("");
      onAnalyzed();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "분석 요청에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <textarea
        value={transcript}
        onChange={(e) => setTranscript(e.target.value)}
        placeholder="예: 검찰청 수사관인데 계좌가 범죄에 연루돼서 지금 즉시 안전계좌로 이체해야 한다고 전화왔어"
        rows={3}
        style={{
          resize: "vertical",
          padding: "10px 12px",
          borderRadius: "6px",
          border: "1px solid var(--border)",
          background: "var(--surface-1)",
          color: "var(--text-primary)",
          fontFamily: "inherit",
          fontSize: "14px",
        }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
        <button
          type="submit"
          disabled={loading || !transcript.trim()}
          style={{
            alignSelf: "flex-start",
            padding: "8px 16px",
            borderRadius: "6px",
            border: "none",
            background: "var(--series-1)",
            color: "#ffffff",
            fontSize: "14px",
            cursor: loading ? "default" : "pointer",
            opacity: loading || !transcript.trim() ? 0.6 : 1,
          }}
        >
          {loading ? "분석 중…" : "분석하기"}
        </button>
        {error && <span style={{ color: "var(--status-critical)", fontSize: "13px" }}>{error}</span>}
      </div>
    </form>
  );
}
