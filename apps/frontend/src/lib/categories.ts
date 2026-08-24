// 패턴 카테고리 → 색상 매핑. apps/mcp-server의 PatternCategory 순서와 고정으로 맞춘다
// (dataviz 스킬: 카테고리 색은 고정 순서로 배정, 순환 금지).
const CATEGORY_COLOR_ORDER: string[] = [
  "authority_impersonation", // 기관사칭 → series-1
  "fear_inducement", // 공포조성 → series-2
  "urgent_transfer", // 긴급송금유도 → series-3
  "personal_info_request", // 개인정보요구 → series-4
];

const SERIES_VARS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

export function colorForCategory(category: string): string {
  const index = CATEGORY_COLOR_ORDER.indexOf(category);
  if (index === -1) {
    // TODO: N-06 확장성 — 새 카테고리가 5번째 이상으로 추가되면 여기 순서에도 등록할 것
    return "var(--text-muted)";
  }
  return SERIES_VARS[index];
}
