import { defineConfig, devices } from "@playwright/test";

// Serves the built viewer same-origin from the real API (create_app), replay only,
// over PL_BUNDLE_DIR (default: the committed test_fake fixture) and two held-out
// decoys that must never be listed (tests/web/wiring_server.py --replay). The live
// and rep specs mock their routes in the browser. No keys, no GPU.
const PORT = 4173;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite build && cd ../.. && uv run python -m tests.web.wiring_server --replay --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/bundles`,
    reuseExistingServer: false,
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
