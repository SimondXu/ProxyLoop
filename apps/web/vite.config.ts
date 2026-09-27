import { defineConfig } from "vitest/config";

// Replay data comes only from the real API (S1-SYS-09): `make replay` serves the
// built web same-origin from `python -m proxyloop.serve.api --web-dir`. For the
// Vite dev server, PL_API_URL (e.g. http://127.0.0.1:8000) proxies /api, /ws,
// /live and /rep to a running API, e.g. `PL_API_URL=http://127.0.0.1:8000 npm
// run replay`. The API must be started with --allow-origin
// http://127.0.0.1:<vite port>; Origin is forwarded unchanged.
const api = process.env.PL_API_URL;
const proxy = api && {
  "/api": api,
  "/ws": { target: api, ws: true },
  "^/(live|rep)/": api,
};

export default defineConfig({
  server: proxy ? { proxy } : {},
  test: { include: ["src/**/*.test.ts"] },
});
