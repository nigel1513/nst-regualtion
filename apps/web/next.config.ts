import type { NextConfig } from "next";

const API = process.env.REG_API_URL ?? "http://127.0.0.1:21061";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API}/api/:path*` }];
  },
};

export default nextConfig;
