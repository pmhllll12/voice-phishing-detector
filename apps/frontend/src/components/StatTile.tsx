import type { RiskLevel } from "@/lib/api";
import { RISK_LEVEL_META } from "@/lib/risk";

// dataviz 스킬: stat tile 계약 — label(문장체, 콜론 없음) + value(굵게, 비례 숫자).
// tone: 위험도 tile일 때만 RISK_LEVEL_META의 색을 재사용한다(색상을 여기서 중복 정의하지
// 않음) — "neutral"(기본값)은 기존 회색 스타일 그대로 유지한다.
export function StatTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  tone?: RiskLevel | "neutral";
}) {
  const meta = tone !== "neutral" ? RISK_LEVEL_META[tone] : null;

  return (
    <div
      style={{
        background: meta ? meta.bg : "var(--surface-1)",
        border: "1px solid var(--border)",
        borderLeft: meta ? `3px solid ${meta.color}` : "1px solid var(--border)",
        borderRadius: "8px",
        padding: "16px 20px",
      }}
    >
      <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>{label}</div>
      <div
        style={{
          fontSize: "32px",
          fontWeight: 600,
          color: meta ? meta.color : "var(--text-primary)",
          marginTop: "4px",
        }}
      >
        {value}
      </div>
    </div>
  );
}
