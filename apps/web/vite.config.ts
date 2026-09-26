import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { bundleApi } from "./server/bundleApi.ts";

const repo = fileURLToPath(new URL("../..", import.meta.url));
// PL_BUNDLE_DIR: one bundle directory or a directory of bundles, relative to the
// repo root (or absolute). Default: the committed test_fake fixture.
export const bundleDir = resolve(repo, process.env.PL_BUNDLE_DIR ?? "tests/web/fixtures");

export default defineConfig({
  plugins: [bundleApi(bundleDir)],
  test: { include: ["src/**/*.test.ts", "server/**/*.test.ts"] },
});
