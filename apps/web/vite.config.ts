import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { bundleApi } from "./server/bundleApi.ts";

const repo = fileURLToPath(new URL("../..", import.meta.url));
// PL_BUNDLE_DIR: one bundle directory or a directory of bundles, relative to the
// repo root (or absolute). Default: the committed test_fake fixture.
export const bundleDir = resolve(repo, process.env.PL_BUNDLE_DIR ?? "tests/web/fixtures");

// PL_API_URL (e.g. http://127.0.0.1:8000): proxy /api, /ws, /live and /rep to the
// real API (S1-SYS-09/10) instead of serving the fixture middleware, e.g.
// `PL_API_URL=http://127.0.0.1:8000 npm run replay`. The API must be started with
// --allow-origin http://127.0.0.1:<vite port>; Origin is forwarded unchanged.
// Unset: the read-only fixture middleware, as before.
const api = process.env.PL_API_URL;
const proxy = api && {
  "/api": api,
  "/ws": { target: api, ws: true },
  "^/(live|rep)/": api,
};

export default defineConfig({
  plugins: api ? [] : [bundleApi(bundleDir)],
  server: proxy ? { proxy } : {},
  test: { include: ["src/**/*.test.ts", "server/**/*.test.ts"] },
});
