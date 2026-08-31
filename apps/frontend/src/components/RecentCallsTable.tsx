"use client";

import { useState } from "react";

import { ApiError, submitReport, type CallAnalysis, type ReportResult } from "@/lib/api";
import { RISK_LEVEL_META } from "@/lib/risk";

type ReportButtonState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "submitted"; result: ReportResult }
  | { status: "error"; message: string };

// F-07: 고위험 판정 건만 신고 접수(mock)를 개시할 수 있다. mcp-server의 신고 기록은
// 아직 call_id와 연결되어 있지 않아(ReportSubmissionService 상단 TODO 참고), 접수
// 여부는 이 버튼의 세션 로컬 상태로만 표시한다 — 새로고침하면 다시 "접수" 상태로 보인다.
function ReportButton({ call }: { call: CallAnalysis }) {
  const [state, setState] = useState<ReportButtonState>({ status: "idle" });

  if (call.risk_level !== "high") {
    return <span style={{ color: "var(--text-muted)" }}>–</span>;
  }

  async function handleClick() {
    setState({ status: "submitting" });
    try {
      const result = await submitReport(call.explanation_summary, call.risk_level);
      setState({ status: "submitted", result });
    } catch (err) {
      setState({ status: "error", message: err instanceof ApiError ? err.message : "신고 접수에 실패했습니다." });
    }
  }

  if (state.status === "submitted") {
    return (
      <span style={{ color: "var(--status-good)", fontSize: "12px" }}>
        접수됨 ({state.result.channel === "auto" ? "자동" : "수동"})
      </span>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
      <button
        type="button"
        onClick={handleClick}
        disabled={state.status === "submitting"}
        style={{
          padding: "4px 10px",
          borderRadius: "6px",
          border: "1px solid var(--status-critical)",
          background: "transparent",
          color: "var(--status-critical)",
          fontSize: "12px",
          cursor: state.status === "submitting" ? "default" : "pointer",
          opacity: state.status === "submitting" ? 0.6 : 1,
        }}
      >
        {state.status === "submitting" ? "접수 중…" : "신고 접수"}
      </button>
      {state.status === "error" && (
        <span style={{ color: "var(--status-critical)", fontSize: "11px" }}>{state.message}</span>
      )}
    </div>
  );
}

export function RecentCallsTable({ calls }: { calls: CallAnalysis[] }) {
  if (calls.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: "14px" }}>
        아직 분석된 통화가 없습니다. 위 폼에서 통화 내용을 입력해 분석해보세요.
      </p>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr
            style={{
              borderBottom: "1px solid var(--gridline)",
              textAlign: "left",
              color: "var(--text-muted)",
            }}
          >
            <th style={{ padding: "8px", fontWeight: 500 }}>시각</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>위험도</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>내용</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>판정 요약</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>신고(F-07)</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const meta = RISK_LEVEL_META[call.risk_level];
            const excerpt =
              call.masked_transcript.length > 60
                ? `${call.masked_transcript.slice(0, 60)}…`
                : call.masked_transcript;

            return (
              <tr key={call.call_id} style={{ borderBottom: "1px solid var(--gridline)" }}>
                <td
                  style={{
                    padding: "8px",
                    color: "var(--text-secondary)",
                    whiteSpace: "nowrap",
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {new Date(call.analyzed_at).toLocaleTimeString("ko-KR")}
                </td>
                <td style={{ padding: "8px", whiteSpace: "nowrap" }}>
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "6px",
                      color: meta.color,
                      fontWeight: 600,
                    }}
                  >
                    <span aria-hidden>{meta.icon}</span>
                    {meta.label} ({call.risk_score})
                  </span>
                </td>
                <td style={{ padding: "8px", maxWidth: "320px", color: "var(--text-primary)" }}>
                  {excerpt}
                </td>
                <td style={{ padding: "8px", color: "var(--text-secondary)" }}>
                  {call.explanation_summary}
                  {call.similar_cases.length > 0 && (
                    <ul style={{ margin: "4px 0 0", paddingLeft: "16px", fontSize: "12px", color: "var(--text-muted)" }}>
                      {call.similar_cases.map((c) => (
                        <li key={c.case_id}>
                          유사 사례: {c.title} ({Math.round(c.similarity * 100)}%)
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td style={{ padding: "8px", whiteSpace: "nowrap" }}>
                  <ReportButton call={call} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
