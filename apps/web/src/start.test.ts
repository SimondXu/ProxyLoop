import { describe, expect, it } from "vitest";
import { dayPart, defaults, maybeStarted, parseOffer, startError, taskName, type LaneKey } from "./start";

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

  it("treats only a definite refusal as 'nothing started' (no second paid session)", () => {
    const f = (status: number, error: string, extra: object = {}) => ({ ok: false as const, status, error, ...extra });
    expect(maybeStarted(f(409, "start", { reason: "busy" }))).toBe(false);
    expect(maybeStarted(f(403, "csrf"))).toBe(false);
    expect(maybeStarted(f(503, "unavailable"))).toBe(false);
    expect(maybeStarted(f(0, "no pl_op_csrf cookie: open /start first", { unsent: true }))).toBe(false);
    expect(maybeStarted(f(0, "no response: TypeError: Failed to fetch"))).toBe(true);
    expect(maybeStarted(f(0, "no case_id in the answer"))).toBe(true);
    expect(maybeStarted(f(503, "Service Unavailable"))).toBe(true); // no serve body
    expect(maybeStarted(f(500, "Internal Server Error"))).toBe(true);
  });

  it("names a task card from its ref's family only, never from a copy table", () => {
    expect(taskName("x-out-of-envelope-approval@1")).toBe("X out of envelope approval");
    expect(taskName("cp-direct-discount")).toBe("Cp direct discount");
    expect(taskName("wire_start-human@2")).toBe("Wire start human");
    expect(taskName("@1")).toBe("@1"); // nothing readable: the ref as sent
  });
});

describe("the start page's greeting (S1-SYS-81)", () => {
  // Local clock, no name: morning 05:00–11:59, afternoon 12:00–17:59, evening 18:00–04:59.
  const at = (h: number, m: number) => new Date(2026, 8, 28, h, m);
  it.each([
    [0, 0, "evening"],
    [4, 59, "evening"],
    [5, 0, "morning"],
    [11, 59, "morning"],
    [12, 0, "afternoon"],
    [17, 59, "afternoon"],
    [18, 0, "evening"],
    [23, 59, "evening"],
  ] as const)("%i:%i is %s", (h, m, part) => {
    expect(dayPart(at(h, m))).toBe(part);
  });
});
