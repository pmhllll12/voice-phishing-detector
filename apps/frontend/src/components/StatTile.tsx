// dataviz 스킬: stat tile 계약 — label(문장체, 콜론 없음) + value(굵게, 비례 숫자).
export function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        background: "var(--surface-1)",
        border: "1px solid var(--border)",
        borderRadius: "8px",
        padding: "16px 20px",
      }}
    >
      <div style={{ fontSize: "13px", color: "var(--text-secondary)" }}>{label}</div>
      <div style={{ fontSize: "32px", fontWeight: 600, color: "var(--text-primary)", marginTop: "4px" }}>
        {value}
      </div>
    </div>
  );
}
