"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import { AnalyzeCallForm } from "@/components/AnalyzeCallForm";
import { DeepvoiceCheckForm } from "@/components/DeepvoiceCheckForm";
import { HorizontalBarList } from "@/components/HorizontalBarList";
import { RecentCallsTable } from "@/components/RecentCallsTable";
import { StatTile } from "@/components/StatTile";
import { getStatsSummary, listCalls, type Channel, type CallAnalysis, type RiskLevel, type StatsSummary } from "@/lib/api";
import { colorForCategory } from "@/lib/categories";
import { CHANNEL_TABS } from "@/lib/channels";
import { RISK_LEVEL_META, RISK_LEVEL_ORDER } from "@/lib/risk";

// F-06 대시보드 UI/UX 개선(2026-09-02, item 5): 목록이 694건까지 쌓였는데 항상 최근
// PAGE_SIZE건만 보여서(listCalls(20) 고정) 더 오래된 판정을 볼 방법이 없었다. 진짜
// OFFSET 기반 페이지네이션 대신 "limit을 늘려서 다시 조회"하는 방식을 쓴다 — list_recent가
// 이미 "최근 N건 중 상위"를 반환하므로, limit만 키우면 이전에 보이던 건들을 그대로 포함한
// 더 큰 결과가 온다(서버/DB 스키마 변경 없이 최소 구현). 데이터가 수만 건 규모로 커지면
// 진짜 OFFSET/cursor 페이지네이션으로 바꿔야 한다.
const PAGE_SIZE = 20;

const sectionTitleStyle: CSSProperties = {
  fontSize: "15px",
  fontWeight: 600,
  marginBottom: "10px",
};

// 코드 리뷰(2026-09-02) 대응: 채널 탭 버튼과 위험도 필터 버튼이 거의 동일한 스타일
// 객체를 각각 인라인으로 들고 있어 중복이었다 — 공통 필터 탭 스타일을 함수로 뽑아
// 두 곳에서 재사용한다. activeColor를 생략하면(채널 탭처럼 강조색이 없는 경우)
// text-primary로 폴백한다.
function filterTabStyle(active: boolean, activeColor?: string): CSSProperties {
  return {
    padding: "6px 14px",
    borderRadius: "6px",
    border: `1px solid ${active && activeColor ? activeColor : "var(--gridline)"}`,
    background: active ? "var(--surface-2)" : "transparent",
    color: active ? (activeColor ?? "var(--text-primary)") : "var(--text-secondary)",
    fontWeight: active ? 600 : 400,
    fontSize: "13px",
    cursor: "pointer",
  };
}

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [calls, setCalls] = useState<CallAnalysis[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  // SMS/email 실채널 연동(2026-09-02): "최근 탐지 현황" 표를 채널별로 걸러서 본다.
  // 목록 자체는 전 채널을 한 번에 받아오고(listCalls), 필터링은 클라이언트에서만
  // 한다 — 채널별 서버사이드 페이지네이션이 필요할 정도의 규모가 아니라서.
  const [channelFilter, setChannelFilter] = useState<Channel | "all">("all");
  // item 5: 위험도 필터(low/medium/high) — 채널 탭과 별개 축이라 AND로 함께 적용한다.
  const [riskFilter, setRiskFilter] = useState<RiskLevel | "all">("all");
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loadingMore, setLoadingMore] = useState(false);
  // 코드 리뷰(2026-09-02) 대응: "더 보기"(limit 증가) 클릭과 10초 자동 폴링이 겹치면 두
  // 요청이 동시에 in-flight 상태가 될 수 있는데, 요청 순서와 응답 도착 순서가 다를 수
  // 있다(예: limit=20 요청이 limit=40 요청보다 늦게 도착) — 그러면 더 큰 결과를 더 작은
  // 결과가 덮어써서 화면이 일시적으로 줄어든다. 매 refresh 호출마다 증가하는 요청 ID를
  // 발급해두고, 응답이 왔을 때 그게 여전히 "가장 최근에 보낸 요청"인 경우에만 state를
  // 갱신한다 — 오래된 응답은 조용히 버린다.
  const latestRequestId = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++latestRequestId.current;
    try {
      const [statsData, callsData] = await Promise.all([getStatsSummary(), listCalls(limit)]);
      if (requestId !== latestRequestId.current) return;
      setStats(statsData);
      setCalls(callsData);
      setLoadError(null);
    } catch {
      if (requestId !== latestRequestId.current) return;
      setLoadError(
        "apps/api에 연결할 수 없습니다. api(8000)와 mcp-server REST 어댑터(8100)가 실행 중인지 확인하세요."
      );
    } finally {
      if (requestId === latestRequestId.current) setLoadingMore(false);
    }
  }, [limit]);

  useEffect(() => {
    refresh();
    // TODO: F-06 "실시간" 요구사항 — 지금은 10초 폴링. 규모가 커지면 WebSocket/SSE로 교체 검토
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

  function handleLoadMore() {
    setLoadingMore(true);
    setLimit((l) => l + PAGE_SIZE);
  }

  const riskItems = RISK_LEVEL_ORDER.map((level) => ({
    key: level,
    label: RISK_LEVEL_META[level].label,
    value: stats?.risk_level_counts[level] ?? 0,
    color: RISK_LEVEL_META[level].color,
    icon: RISK_LEVEL_META[level].icon,
  }));

  const categoryItems = (stats?.category_counts ?? []).map((c) => ({
    key: c.category,
    label: c.category_label,
    value: c.count,
    color: colorForCategory(c.category),
  }));

  return (
    <main style={{ maxWidth: "960px", margin: "0 auto", padding: "32px 24px" }}>
      <h1 style={{ fontSize: "22px", marginBottom: "4px" }}>보이스피싱 탐지 관제 대시보드</h1>
      <p style={{ color: "var(--text-secondary)", fontSize: "14px", marginTop: 0 }}>
        F-06 — 탐지 현황 / 위험도 분포 / 처리 통계 (10초마다 자동 갱신)
      </p>

      {loadError && (
        <div
          style={{
            background: "var(--surface-1)",
            border: "1px solid var(--status-critical)",
            color: "var(--status-critical)",
            borderRadius: "6px",
            padding: "10px 14px",
            fontSize: "13px",
            marginBottom: "20px",
          }}
        >
          {loadError}
        </div>
      )}

      <section style={{ marginBottom: "28px" }}>
        <h2 style={sectionTitleStyle}>통화 분석해보기</h2>
        <AnalyzeCallForm onAnalyzed={refresh} />
      </section>

      <section style={{ marginBottom: "28px" }}>
        <h2 style={sectionTitleStyle}>딥보이스 판별해보기 (F-03)</h2>
        <DeepvoiceCheckForm />
      </section>

      <section
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: "12px",
          marginBottom: "28px",
        }}
      >
        <StatTile label="총 분석 건수" value={stats?.total_analyzed ?? "–"} />
        <StatTile label="고위험 건수" value={stats?.risk_level_counts.high ?? "–"} />
        <StatTile label="중위험 건수" value={stats?.risk_level_counts.medium ?? "–"} />
        <StatTile label="저위험 건수" value={stats?.risk_level_counts.low ?? "–"} />
      </section>

      <section style={{ marginBottom: "28px" }}>
        <h2 style={sectionTitleStyle}>위험도 분포</h2>
        <HorizontalBarList items={riskItems} />
      </section>

      <section style={{ marginBottom: "28px" }}>
        <h2 style={sectionTitleStyle}>탐지 패턴 카테고리</h2>
        {categoryItems.length > 0 ? (
          <HorizontalBarList items={categoryItems} />
        ) : (
          <p style={{ color: "var(--text-muted)", fontSize: "14px" }}>아직 탐지된 패턴이 없습니다.</p>
        )}
      </section>

      <section>
        <h2 style={sectionTitleStyle}>최근 탐지 현황</h2>
        <div style={{ display: "flex", gap: "6px", marginBottom: "8px" }}>
          {CHANNEL_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              onClick={() => setChannelFilter(tab.key)}
              style={filterTabStyle(channelFilter === tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {/* item 5: 위험도 필터 — 채널 탭과 같은 스타일을 재사용하되, 선택된 위험도는
            RISK_LEVEL_META 색으로 강조해 채널 탭과 구분되는 축임을 드러낸다. */}
        <div style={{ display: "flex", gap: "6px", marginBottom: "12px" }}>
          <button type="button" onClick={() => setRiskFilter("all")} style={filterTabStyle(riskFilter === "all")}>
            전체 위험도
          </button>
          {RISK_LEVEL_ORDER.map((level) => {
            const meta = RISK_LEVEL_META[level];
            return (
              <button
                key={level}
                type="button"
                onClick={() => setRiskFilter(level)}
                style={filterTabStyle(riskFilter === level, meta.color)}
              >
                <span aria-hidden>{meta.icon}</span> {meta.label}
              </button>
            );
          })}
        </div>
        <RecentCallsTable
          calls={calls
            .filter((c) => channelFilter === "all" || c.channel === channelFilter)
            .filter((c) => riskFilter === "all" || c.risk_level === riskFilter)}
        />
        {calls.length >= limit && (
          <div style={{ textAlign: "center", marginTop: "14px" }}>
            <button
              type="button"
              onClick={handleLoadMore}
              disabled={loadingMore}
              style={{
                padding: "8px 20px",
                borderRadius: "6px",
                border: "1px solid var(--gridline)",
                background: "transparent",
                color: "var(--text-secondary)",
                fontSize: "13px",
                cursor: loadingMore ? "default" : "pointer",
                opacity: loadingMore ? 0.6 : 1,
              }}
            >
              {loadingMore ? "불러오는 중…" : "더 보기"}
            </button>
          </div>
        )}
      </section>
    </main>
  );
}
