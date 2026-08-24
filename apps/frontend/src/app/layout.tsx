import "./globals.css";

export const metadata = {
  title: "보이스피싱 탐지 관제 대시보드",
  description: "F-06: 실시간 탐지 현황/통계 시각화",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
