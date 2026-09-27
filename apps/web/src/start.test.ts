import { describe, expect, it } from "vitest";
import { defaults, parseOffer, startError, type LaneKey } from "./start";

const option = (id: string, lane: LaneKey | "ear", isDefault = false, extra: Record<string, unknown> = {}) => ({
  id,
  lane,
  label: `label ${id}`,
  endpoint: "vllm",
  model_id: `model-${id}`,
  default: isDefault,
  ...extra,
});

describe("the start page's options (GET /api/models)", () => {
  it("keeps every option as sent and each lane's one default", () => {
    const options = [option("q", "fast_user", true), option("q2", "fast_user"), option("c", "fast_cp", true), option("s", "slow", true)];
    const offer = parseOffer({ options, tasks: ["cp-direct-discount"] });
    expect(offer).toEqual({ options, tasks: ["cp-direct-discount"] });
    expect(defaults(options as Parameters<typeof defaults>[0])).toEqual({ fast_user: "q", fast_cp: "c", slow: "s" });
    expect(parseOffer({ options: [], tasks: [] })).toEqual({ options: [], tasks: [] }); // a lane without options is allowed
  });

  it("refuses, never repairs, an answer that breaks serve's promises", () => {
    expect(parseOffer({ options: [] })).toBe("the answer is not {options, tasks}");
    expect(parseOffer({ options: [], tasks: [1] })).toBe("a task is not a string");
    expect(parseOffer({ options: [option("x", "ear", true)], tasks: [] })).toMatch(/^a malformed option/);
    expect(parseOffer({ options: [option("x", "slow", true, { endpoint: null })], tasks: [] })).toMatch(/^a malformed option/);
    expect(parseOffer({ options: [option("a", "slow"), option("b", "slow")], tasks: [] })).toBe("lane slow does not have exactly one default");
    expect(parseOffer({ options: [option("a", "slow", true), option("b", "slow", true)], tasks: [] })).toBe(
      "lane slow does not have exactly one default",
    );
  });

  it("shows each refusal with its status, reason and meaning", () => {
    expect(startError({ ok: false, status: 409, error: "start", reason: "busy" })).toBe(
      "409 start: busy (a session is already running: wait for it to end)",
    );
    expect(startError({ ok: false, status: 400, error: "start", reason: "unknown_model" })).toBe(
      "400 start: unknown_model (the kernel does not know a chosen model)",
    );
    expect(startError({ ok: false, status: 403, error: "csrf" })).toBe("403 csrf (no valid operator cookie: open /start)");
    expect(startError({ ok: false, status: 503, error: "unavailable" })).toMatch(/^503 unavailable \(/);
    expect(startError({ ok: false, status: 422, error: "invalid body" })).toBe("422 invalid body (the server refused the form)");
    expect(startError({ ok: false, status: 0, error: "no response: offline" })).toBe("no response: offline");
  });
});
