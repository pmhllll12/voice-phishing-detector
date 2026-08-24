// 가로 막대 목록 — dataviz 스킬 마크 스펙 준수: 두께 18px(≤24px), 데이터 끝(오른쪽)만
// 4px 라운드·기준선(왼쪽)은 사각형, 트랙(연한 배경)으로 상대 비율을 항상 보이게 함.
// 값은 막대 끝에 직접 라벨링 (텍스트는 색을 입히지 않고 text 토큰만 사용).

export interface BarItem {
  key: string;
  label: string;
  value: number;
  color: string;
  icon?: string;
}

export function HorizontalBarList({ items, maxValue }: { items: BarItem[]; maxValue?: number }) {
  const max = maxValue ?? Math.max(1, ...items.map((i) => i.value));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
      {items.map((item) => {
        const pct = Math.max(0, Math.min(100, (item.value / max) * 100));
        return (
          <div key={item.key} style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div
              style={{
                width: "130px",
                flexShrink: 0,
                fontSize: "13px",
                color: "var(--text-secondary)",
                display: "flex",
                alignItems: "center",
                gap: "6px",
              }}
            >
              {item.icon && (
                <span aria-hidden style={{ color: item.color, fontSize: "10px" }}>
                  {item.icon}
                </span>
              )}
              <span>{item.label}</span>
            </div>
            <div
              style={{
                flex: 1,
                background: "var(--track)",
                borderRadius: "4px",
                height: "18px",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: "100%",
                  background: item.color,
                  borderRadius: "0 4px 4px 0",
                  minWidth: item.value > 0 ? "4px" : 0,
                  transition: "width 0.3s ease",
                }}
              />
            </div>
            <div
              style={{
                width: "32px",
                textAlign: "right",
                fontSize: "13px",
                color: "var(--text-primary)",
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {item.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}
