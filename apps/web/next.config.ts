import type { NextConfig } from "next";

import { runtimeOrigin } from "./lib/runtime-origin";

// Phase 07 D2: the Runtime origin is loopback-only and defaults to
// http://127.0.0.1:8000; an invalid PROXYLOOP_RUNTIME_ORIGIN fails the build.
const RUNTIME_ORIGIN = runtimeOrigin(process.env.PROXYLOOP_RUNTIME_ORIGIN);

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        destination: `${RUNTIME_ORIGIN}/:path*`,
        source: "/api/runtime/:path*",
      },
    ];
  },
};

export default nextConfig;
