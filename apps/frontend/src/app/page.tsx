"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { AnalyzeCallForm } from "@/components/AnalyzeCallForm";
import { HorizontalBarList } from "@/components/HorizontalBarList";
import { RecentCallsTable } from "@/components/RecentCallsTable";
import { StatTile } from "@/components/StatTile";
import { getStatsSummary, listCalls, type CallAnalysis, type StatsSummary } from "@/lib/api";
import { colorForCategory } from "@/lib/categories";
import { RISK_LEVEL_META, RISK_LEVEL_ORDER } from "@/lib/risk";

const sectionTitleStyle: CSSProperties = {
  fontSize: "15px",
  fontWeight: 600,
  marginBottom: "10px",
};

export default function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [calls, setCalls] = useState<CallAnalysis[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [statsData, callsData] = await Promise.all([getStatsSummary(), listCalls(20)]);
      setStats(statsData);
      setCalls(callsData);
      setLoadError(null);
    } catch {
      setLoadError(
        "apps/api에 연결할 수 없습니다. api(8000)와 mcp-server REST 어댑터(8100)가 실행 중인지 확인하세요."
      );
    }
  }, []);

  useEffect(() => {
    refresh();
    // TODO: F-06 "실시간" 요구사항 — 지금은 10초 폴링. 규모가 커지면 WebSocket/SSE로 교체 검토
    const interval = setInterval(refresh, 10000);
    return () => clearInterval(interval);
  }, [refresh]);

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
        <RecentCallsTable calls={calls} />
      </section>
    </main>
  );
}
