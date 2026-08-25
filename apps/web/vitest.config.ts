import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    setupFiles: [new URL("./vitest.setup.ts", import.meta.url).pathname],
  },
});
