import "./globals.css";

export const metadata = {
  title: "박민호 — Portfolio",
  description: "AI / Cloud Infrastructure Engineer 포트폴리오",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
