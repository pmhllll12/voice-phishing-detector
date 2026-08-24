import type { RiskLevel } from "./api";

// 위험도(상태) 팔레트 매핑 — 절대 카테고리 색과 섞지 않는다 (dataviz 스킬: status palette는
// good/warning/critical 전용이며 시리즈 색과 별개).
export const RISK_LEVEL_META: Record<RiskLevel, { label: string; color: string; icon: string }> = {
  low: { label: "저위험", color: "var(--status-good)", icon: "●" },
  medium: { label: "중위험", color: "var(--status-warning)", icon: "▲" },
  high: { label: "고위험", color: "var(--status-critical)", icon: "■" },
};

export const RISK_LEVEL_ORDER: RiskLevel[] = ["low", "medium", "high"];
