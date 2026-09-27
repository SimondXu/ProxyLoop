import { defineConfig, devices } from "@playwright/test";
import { PORTS } from "./e2e-demo/ports";

// The keys-free demo E2E (S1-SYS-32): the built web served same-origin by the real
// API (create_app) with a test-only Starter (tests/support/web_demo.py) that runs the
// real kernel (run_session, Guard, the fence, the SimRep's policy) on scripted
// test_fake models. One server per scenario (tests/web/demo_server.py), each with its
// own tmp runs root and one live case. Nothing is mocked in the browser; no keys, no GPU.
const ports = Object.values(PORTS)
  .map((p) => `--port ${p}`)
  .join(" ");

export default defineConfig({
  testDir: "e2e-demo",
  timeout: 150_000, // the session runs on the wall clock: speech, holds and read-backs
  fullyParallel: true,
  workers: 3,
  projects: [{ name: "demo", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite build && cd ../.. && uv run python -m tests.web.demo_server ${ports}`,
    url: `http://127.0.0.1:${PORTS.human}/api/bundles`,
    reuseExistingServer: false,
    timeout: 120_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 10_000 },
  },
});
