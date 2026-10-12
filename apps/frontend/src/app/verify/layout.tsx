// 역방향 신원확인 POC(모의 시제품) 공통 레이아웃. 기존 랜딩(/)·관제 대시보드(/dashboard)와
// 분리된 별도 화면군이다. 모든 화면 하단에 "모의 시연" 고지를 고정으로 붙인다 — 실제
// 모바일신분증/정부 시스템과 연동된 것처럼 보이면 안 된다(기관 로고·실제 앱 디자인도 쓰지 않음).

import { MOCK_NOTICE } from "@/lib/verify";

export const metadata = {
  title: "역방향 신원확인 (모의 시연)",
  description: "기관 직원이 먼저 자신을 증명하는 구조를 모사한 시제품 — 실제 모바일신분증과 연동되지 않음",
};

export default function VerifyLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="verify-screen">
      <main style={{ flex: 1, width: "100%", maxWidth: "560px", margin: "0 auto", padding: "24px 16px" }}>
        {children}
      </main>
      <footer
        role="note"
        style={{
          borderTop: "1px solid var(--border)",
          padding: "16px",
          textAlign: "center",
          fontSize: "20px",
          color: "var(--text-secondary)",
          background: "var(--surface-1)",
        }}
      >
        ⓘ {MOCK_NOTICE}
      </footer>
    </div>
  );
}
