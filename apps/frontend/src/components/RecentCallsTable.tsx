"use client";

import { useMemo, useState } from "react";

import { ApiError, submitReport, type CallAnalysis, type ReportResult } from "@/lib/api";
import { CHANNEL_META } from "@/lib/channels";
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

// F-06 대시보드 UI/UX 개선(2026-09-02, item 2): 근거 문장의 "다른 채널 기록"을 클릭하면
// 그 기록의 행으로 스크롤 이동 + 잠깐 하이라이트한다. call.call_id 기준 DOM id를 부여해두고
// (아래 `<tr id={...}>`) scrollIntoView로 이동한다 — 별도 라우팅/모달 없이 같은 표 안에서만
// 동작하는 가벼운 구현이다. 대상이 현재 렌더링된 목록에 없으면(다른 채널 탭 필터에 걸렸거나
// "최근 N건" 밖으로 밀려난 경우) 조용히 무시한다 — 그런 경우는 CorrelationReasons가 애초에
// 링크를 렌더링하지 않는다(아래 참고).
function rowDomId(callId: string) {
  return `call-row-${callId}`;
}

function CorrelationReasons({
  matches,
  knownCallIds,
  onJumpTo,
}: {
  matches: CallAnalysis["correlation_matches"];
  knownCallIds: Set<string>;
  onJumpTo: (callId: string) => void;
}) {
  if (matches.length === 0) return null;
  return (
    <ul style={{ margin: "4px 0 0", paddingLeft: "16px", fontSize: "12px", color: "var(--text-muted)" }}>
      {matches.map((m, i) => {
        const linkable = m.source_call_id !== null && knownCallIds.has(m.source_call_id);
        return (
          <li key={i}>
            {m.reason}
            {linkable && (
              <>
                {" — "}
                <button
                  type="button"
                  onClick={() => onJumpTo(m.source_call_id as string)}
                  style={{
                    background: "none",
                    border: "none",
                    padding: 0,
                    color: "var(--status-info, #4f8dfd)",
                    textDecoration: "underline",
                    cursor: "pointer",
                    font: "inherit",
                  }}
                >
                  해당 기록 보기
                </button>
              </>
            )}
          </li>
        );
      })}
    </ul>
  );
}

// F-06 대시보드 UI/UX 개선(2026-09-02, item 4): "내용" 열이 이전엔 60자로 잘라 보여줘서
// 긴 통화/이메일 내용은 판정 근거를 눈으로 대조해볼 수 없었다. 이제 셀 자체는 2줄로만
// 잘라 보여주고(line-clamp), 클릭하면 전체 내용을 패널로 펼친다 — 새 모달 라이브러리 없이
// 기존 스타일(surface/gridline 변수, 얕은 오버레이)만으로 구현한다.
function ContentModal({ call, onClose }: { call: CallAnalysis; onClose: () => void }) {
  return (
    <div
      role="presentation"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px",
        zIndex: 50,
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--surface-1)",
          border: "1px solid var(--gridline)",
          borderRadius: "8px",
          padding: "20px",
          maxWidth: "560px",
          maxHeight: "80vh",
          overflowY: "auto",
          fontSize: "13px",
          color: "var(--text-primary)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "10px" }}>
          <strong>
            {CHANNEL_META[call.channel]?.icon ?? "❓"} {CHANNEL_META[call.channel]?.label ?? call.channel} 전체 내용
          </strong>
          <button
            type="button"
            onClick={onClose}
            aria-label="닫기"
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              fontSize: "16px",
              cursor: "pointer",
              lineHeight: 1,
              padding: 0,
            }}
          >
            ✕
          </button>
        </div>
        <p style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{call.masked_transcript}</p>
      </div>
    </div>
  );
}

export function RecentCallsTable({ calls }: { calls: CallAnalysis[] }) {
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const [expandedCall, setExpandedCall] = useState<CallAnalysis | null>(null);
  // 코드 리뷰(2026-09-02) 대응: calls prop이 바뀔 때만 다시 만들면 되는데, 매 렌더마다
  // (예: highlightedId만 바뀌는 클릭, 모달 열기/닫기) 새 Set을 만들고 있었다.
  const knownCallIds = useMemo(() => new Set(calls.map((c) => c.call_id)), [calls]);

  function handleJumpTo(callId: string) {
    const el = document.getElementById(rowDomId(callId));
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedId(callId);
    window.setTimeout(() => setHighlightedId((cur) => (cur === callId ? null : cur)), 2000);
  }

  if (calls.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: "14px" }}>
이 채널에서 아직 분석된 건이 없습니다. 통화는 위 폼에서, 이메일은 Gmail 폴러
        (`scripts/poll_gmail_inbox.py`)를 실행해 확인해보세요.
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
            <th style={{ padding: "8px", fontWeight: 500 }}>채널</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>위험도</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>내용</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>판정 요약</th>
            <th style={{ padding: "8px", fontWeight: 500 }}>신고(F-07)</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => {
            const meta = RISK_LEVEL_META[call.risk_level];
            const isHighlighted = call.call_id === highlightedId;

            return (
              <tr
                key={call.call_id}
                id={rowDomId(call.call_id)}
                style={{
                  borderBottom: "1px solid var(--gridline)",
                  background: isHighlighted ? "var(--surface-2)" : undefined,
                  transition: "background 0.3s ease",
                }}
              >
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
                <td style={{ padding: "8px", whiteSpace: "nowrap", color: "var(--text-secondary)" }}>
                  <span aria-hidden>{CHANNEL_META[call.channel]?.icon ?? "❓"}</span>{" "}
                  {CHANNEL_META[call.channel]?.label ?? call.channel}
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
                  {/* F-06 대시보드 item 3: 배지(가산 후 최종점수)와 판정 근거 문단 안 점수
                      (가산 전 원점수)가 서로 다를 때 이 둘의 관계를 배지 바로 옆에서 바로
                      보여준다 — 두 숫자가 왜 다른지 판정 요약 문단까지 읽지 않아도 되게. */}
                  {call.base_risk_score !== call.risk_score && (
                    <span
                      style={{
                        display: "block",
                        fontSize: "11px",
                        color: "var(--text-muted)",
                        marginTop: "2px",
                      }}
                    >
                      {call.base_risk_score} → {call.risk_score} (크로스채널 가산)
                    </span>
                  )}
                </td>
                <td style={{ padding: "8px", maxWidth: "320px", color: "var(--text-primary)" }}>
                  {/* 코드 리뷰(2026-09-02) 대응: 이 열의 폭을 <td>의 maxWidth에만 맡기면
                      기본 table-layout(auto)에서 다른 셀의 내용에 따라 컬럼 폭 계산이
                      그 max-width를 무시할 수 있다 — 특히 줄바꿈 지점이 없는 아주 긴
                      토큰/URL이 들어오면 line-clamp가 걸리기 전에 컬럼 자체가 늘어난다.
                      block 요소에 고정 width를 명시적으로 주면(내용 길이와 무관한
                      preferred width가 되므로) 그 문제가 없다 — <td>의 maxWidth는
                      좁은 화면에서의 보조 안전장치로 남겨둔다. */}
                  <button
                    type="button"
                    onClick={() => setExpandedCall(call)}
                    title="클릭해서 전체 내용 보기"
                    style={{
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      textAlign: "left",
                      width: "320px",
                      maxWidth: "100%",
                      background: "none",
                      border: "none",
                      padding: 0,
                      margin: 0,
                      color: "inherit",
                      font: "inherit",
                      cursor: "pointer",
                    }}
                  >
                    {call.masked_transcript}
                  </button>
                </td>
                <td style={{ padding: "8px", color: "var(--text-secondary)" }}>
                  {call.explanation_summary}
                  <CorrelationReasons
                    matches={call.correlation_matches}
                    knownCallIds={knownCallIds}
                    onJumpTo={handleJumpTo}
                  />
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
      {expandedCall && <ContentModal call={expandedCall} onClose={() => setExpandedCall(null)} />}
    </div>
  );
}
