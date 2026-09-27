import { defineConfig, devices } from "@playwright/test";

// Serves the built viewer with the read-only bundle API over PL_BUNDLE_DIR
// (default: the committed test_fake fixture). No keys, no GPU.
const PORT = 4173;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
