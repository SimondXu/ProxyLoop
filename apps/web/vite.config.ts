import { defineConfig } from "vitest/config";

// Replay data comes only from the real API (S1-SYS-09): `make replay` serves the
// built web same-origin from `python -m proxyloop.serve.api --web-dir`. The Vite
// dev server (`npm run dev`) needs PL_API_URL (e.g. http://127.0.0.1:8000): it
// proxies /api, /ws, /live and /rep to a running API, e.g.
// `PL_API_URL=http://127.0.0.1:8000 npm run dev`. The API must be started with
// --allow-origin http://127.0.0.1:<vite port>; Origin is forwarded unchanged.
const api = process.env.PL_API_URL;
const proxy = api && {
  "/api": api,
  "/ws": { target: api, ws: true },
  "^/(live|rep)/": api,
};

export default defineConfig(({ command, mode, isPreview }) => {
  if (command === "serve" && !isPreview && mode !== "test" && !api) {
    throw new Error(
      "The Vite dev server has no replay data of its own: set PL_API_URL to a running " +
        "API (python -m proxyloop.serve.api --allow-origin http://127.0.0.1:<vite port>), " +
        "or run `make replay`.",
    );
  }
  return {
    server: proxy ? { proxy } : {},
    test: { include: ["src/**/*.test.ts"] },
  };
});
