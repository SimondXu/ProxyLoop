import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        destination: "http://127.0.0.1:8000/:path*",
        source: "/api/runtime/:path*",
      },
    ];
  },
};

export default nextConfig;
