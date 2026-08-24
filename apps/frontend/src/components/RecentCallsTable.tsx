import type { CallAnalysis } from "@/lib/api";
import { RISK_LEVEL_META } from "@/lib/risk";

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
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const meta = RISK_LEVEL_META[call.risk_level];
            const excerpt =
              call.raw_transcript.length > 60
                ? `${call.raw_transcript.slice(0, 60)}…`
                : call.raw_transcript;

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
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
