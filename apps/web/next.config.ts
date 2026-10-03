import type { NextConfig } from "next";

const API = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

const nextConfig: NextConfig = {
  // 질의응답은 LLM 생성으로 수십 초 걸릴 수 있다 (기본 프록시 제한 30초)
  experimental: { proxyTimeout: 120_000 },
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
