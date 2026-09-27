import { defineConfig, devices } from "@playwright/test";

// The web↔API wiring drift test (S1-SYS-18): the built web served same-origin by
// the real API (create_app) over stub cases in a tmp root and evidence/s0, read
// only (tests/web/wiring_server.py). No mocks in the browser; no keys, no GPU.
const PORT = 4180;

export default defineConfig({
  testDir: "e2e-wiring",
  timeout: 30_000,
  workers: 1, // one server: each test owns its case, and the order stays readable
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [{ name: "wiring", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite build && cd ../.. && uv run python -m tests.web.wiring_server --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/bundles`,
    reuseExistingServer: false,
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
