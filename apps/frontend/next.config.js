/** @type {import('next').NextConfig} */
// 외부 공개(Cloudflare 터널) 시 브라우저가 localhost 백엔드를 직접 부를 수 없으므로,
// NEXT_PUBLIC_API_BASE_URL=/_api, NEXT_PUBLIC_VERIFY_WORKER_URL=/_verify 로 빌드하면
// 같은 오리진 경로를 Next 서버가 내부 백엔드로 프록시한다. 기본(localhost 직접 호출)에는 영향 없음.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://localhost:8000";
const VERIFY_PROXY_TARGET = process.env.VERIFY_PROXY_TARGET ?? "http://localhost:8400";

const nextConfig = {
  experimental: {
    // 음성 업로드 분석(STT+딥보이스)은 30초 기본 프록시 타임아웃을 넘길 수 있다.
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return [
      { source: "/_api/:path*", destination: `${API_PROXY_TARGET}/:path*` },
      { source: "/_verify/:path*", destination: `${VERIFY_PROXY_TARGET}/:path*` },
    ];
  },
};

module.exports = nextConfig;
