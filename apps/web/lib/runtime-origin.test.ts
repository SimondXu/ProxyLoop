import { describe, expect, it } from "vitest";

import { DEFAULT_RUNTIME_ORIGIN, runtimeOrigin } from "./runtime-origin";

describe("runtimeOrigin (Phase 07 D2)", () => {
  it("defaults to the loopback Runtime on port 8000", () => {
    expect(DEFAULT_RUNTIME_ORIGIN).toBe("http://127.0.0.1:8000");
    expect(runtimeOrigin(undefined)).toBe("http://127.0.0.1:8000");
    expect(runtimeOrigin("")).toBe("http://127.0.0.1:8000");
  });

  it("accepts an explicit loopback origin", () => {
    expect(runtimeOrigin("http://127.0.0.1:8011")).toBe("http://127.0.0.1:8011");
    expect(runtimeOrigin("http://localhost:8011")).toBe("http://localhost:8011");
    expect(runtimeOrigin("http://[::1]:8011")).toBe("http://[::1]:8011");
    expect(runtimeOrigin("http://127.0.0.1:8011/")).toBe("http://127.0.0.1:8011");
  });

  it.each([
    "http://example.com:8000",
    "http://10.0.0.5:8000",
    "https://127.0.0.1:8000",
    "http://user:secret@127.0.0.1:8000",
    "http://127.0.0.1:8000/api",
    "http://127.0.0.1:8000?x=1",
    "http://127.0.0.1:8000#x",
    "http://127.0.0.1",
    "127.0.0.1:8000",
    "not a url",
  ])("refuses %s so the build fails closed", (value) => {
    expect(() => runtimeOrigin(value)).toThrow(/PROXYLOOP_RUNTIME_ORIGIN/);
  });
});
