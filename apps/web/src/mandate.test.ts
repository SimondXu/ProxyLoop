import { describe, expect, it } from "vitest";
import type { Posting } from "./approval";
import { mandateBody } from "./liveApi";
import { limitRows, limitsStatusText, mandateCards } from "./mandate";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, wall?: string): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream: "agent", cause_ids: [], payload, wall };
};
const H = (id: string) => `${id}`.padEnd(64, "0");
const proposed = (id: string, extra: Ev["payload"] = {}) =>
  ev("mandate.proposed", "guard", {
    mandate_id: id,
    mandate_hash: H(id),
    status: "proposed",
    epoch: 1,
    max_monthly_price_minor: 6500,
    max_term_months: 24,
    max_one_time_fees_minor: 0,
    required_features: [],
    forbidden_changes: [],
    expires_ms: null,
    decided_by: null,
    ...extra,
  });
const post = (id: string, decision = "granted", actor = "ui") =>
  ev("approval.post", actor, { subject: "mandate", subject_id: id, decision, subject_hash: H(id), authority_epoch: 1 });
const decided = (id: string, decision: string, by = "ui", actor = "kernel") =>
  ev("mandate.decided", actor, { mandate_id: id, mandate_hash: H(id), decision, by }, "2026-09-27T14:30:00Z");
const bump = (n: number, reason: string, actor = "kernel") => ev("authority.epoch", actor, { new: n, reason });
const none = new Map<string, Posting>();
const one = (events: Ev[], posts = none) => {
  const [view, ...rest] = mandateCards(events, posts);
  expect(rest).toEqual([]);
  return view && { status: view.status, by: view.by, reason: view.reason };
};
const at = (m: Map<string, Posting>) => m;

describe("limits card state (I6: only a click posts; only mandate.decided decides)", () => {
  it("opens on guard's mandate.proposed; a proposal by any other actor is ignored", () => {
    expect(one([proposed("m1")])).toEqual({ status: "open", by: null, reason: null });
    expect(mandateCards([{ ...proposed("m1"), actor: "slow" }], none)).toEqual([]);
  });

  it("posts exactly {decision, mandate_hash, authority_epoch} from mandate.proposed", () => {
    const [v] = mandateCards([proposed("m1", { epoch: 3 })], none);
    expect(v && mandateBody(v.mandate, "granted")).toEqual({ decision: "granted", mandate_hash: H("m1"), authority_epoch: 3 });
  });

  it.each(["granted", "denied"])("open → pending → sent → decided %s", (decision) => {
    const events = [proposed("m1")];
    expect(one(events, at(new Map([["m1", "pending"]])))?.status).toBe("pending");
    const ok = at(new Map([["m1", { ok: true }]]));
    expect(one(events, ok)?.status).toBe("sent");
    events.push(post("m1", decision));
    expect(one(events, none)?.status).toBe("sent");
    events.push(decided("m1", decision));
    expect(one(events, ok)).toEqual({ status: decision, by: "ui", reason: null });
  });

  it("a 200 or a decision from a non-kernel actor never decides", () => {
    const ok = at(new Map([["m1", { ok: true }]]));
    expect(one([proposed("m1"), decided("m1", "granted", "ui", "ui")], ok)?.status).toBe("sent");
    expect(one([proposed("m1"), decided("m1", "granted", "ui", "slow")])?.status).toBe("open");
    expect(one([proposed("m1"), decided("m2", "granted")])?.status).toBe("open");
  });

  it("by ui vs by sim_approver, each in its own words", () => {
    const [mine] = mandateCards([proposed("m1"), post("m1"), decided("m1", "granted")], none);
    expect(mine && limitsStatusText(mine)).toMatch(/^Confirmed by you · \d{1,2}:\d{2}\s?[AP]M$/);
    const sim = [proposed("m1"), post("m1", "granted", "sim_approver"), decided("m1", "granted", "sim_approver")];
    const [v] = mandateCards(sim, none);
    expect(v?.by).toBe("sim_approver");
    expect(v && limitsStatusText(v)).toBe("Confirmed by the simulated approver (not you)");
    const [no] = mandateCards([proposed("m1"), decided("m1", "denied", "sim_approver")], none);
    expect(no && limitsStatusText(no)).toBe("Declined by the simulated approver (not you)");
  });

  it("is superseded by a newer guard mandate.proposed", () => {
    const views = mandateCards([proposed("m1"), proposed("m2")], none);
    expect(views.map((v) => [v.mandate.mandate_id, v.status])).toEqual([
      ["m1", "superseded"],
      ["m2", "open"],
    ]);
  });

  it("goes stale when the epoch moves past an undecided proposal", () => {
    expect(one([proposed("m1"), bump(1, "slow_revoke")])?.status).toBe("open");
    expect(one([proposed("m1"), bump(2, "slow_revoke")])).toEqual({ status: "stale", by: null, reason: "epoch_moved" });
    expect(one([proposed("m1"), bump(2, "slow_revoke", "fast.user")])?.status).toBe("open");
  });

  it("goes stale on a 409 stale with its reason, and shows already_decided; other failures leave it open", () => {
    const res = (status: number, error: string, reason?: string) => at(new Map<string, Posting>([["m1", { ok: false, status, error, reason }]]));
    expect(one([proposed("m1")], res(409, "stale", "no_proposal"))).toEqual({ status: "stale", by: null, reason: "no_proposal" });
    expect(one([proposed("m1")], res(409, "stale"))).toEqual({ status: "stale", by: null, reason: null });
    expect(one([proposed("m1")], res(409, "already_decided", "already_decided"))?.status).toBe("already_decided");
    for (const [s, e] of [
      [403, "csrf"],
      [404, "unknown case"],
      [422, "invalid body"],
      [503, "unavailable"],
      [0, "no response: offline"],
    ] as const) {
      const [v] = mandateCards([proposed("m1")], res(s, e));
      expect([v?.status, v?.error]).toEqual(["open", s ? `${s} ${e}` : e]);
    }
  });

  it("is refused by the kernel's action.denied{approval.post} citing the proposal", () => {
    const req = proposed("m1");
    const denied = { ...ev("action.denied", "kernel", { intent: "approval.post", reason: "subject_hash_mismatch" }), cause_ids: [req.event_id] };
    expect(one([req, denied], at(new Map([["m1", { ok: true }]])))).toEqual({ status: "refused", by: null, reason: "subject_hash_mismatch" });
    expect(one([req, { ...denied, actor: "slow" }])?.status).toBe("open");
  });

  it("a granted mandate keeps its own mandate_decided bump, then is tightened or withdrawn", () => {
    const granted = [proposed("m1"), post("m1"), decided("m1", "granted"), bump(2, "mandate_decided")];
    expect(one(granted)?.status).toBe("granted");
    const tight = mandateCards([...granted, bump(3, "tighten_mandate"), proposed("m2", { epoch: 3 })], none);
    expect(tight.map((v) => v.status)).toEqual(["tightened", "open"]);
    expect(one([...granted, bump(3, "slow_revoke")])?.status).toBe("withdrawn");
    expect(one([...granted, bump(3, "f2s_revoke")])?.status).toBe("withdrawn");
  });

  it("every status has words, and no undecided status says confirmed", () => {
    const text = (status: string) => limitsStatusText({ status, by: null, at: null, reason: null } as never);
    for (const s of ["open", "pending", "sent"]) expect(text(s)).not.toMatch(/confirm(ed)? by|approved/i);
    expect(text("sent")).toBe("Sent. Waiting for Guard to record it");
    expect(text("stale")).toBe("No longer valid");
    expect(limitsStatusText({ status: "stale", by: null, at: null, reason: "epoch_moved" } as never)).toBe(
      "No longer valid: your instructions changed",
    );
    expect(limitsStatusText({ status: "stale", by: null, at: null, reason: "weird_new_reason" } as never)).toBe(
      "No longer valid: weird_new_reason",
    );
    expect(text("tightened")).toMatch(/^Tightened/);
    expect(text("withdrawn")).toMatch(/^Withdrawn/);
  });

  it("shows the limits as labels, never computed", () => {
    const [v] = mandateCards([proposed("m1", { required_features: ["hotspot"], forbidden_changes: ["port_out"] })], none);
    expect(v && limitRows(v.mandate)).toEqual([
      ["Monthly price", "up to $65.00"],
      ["Contract", "up to 24 months"],
      ["One-time fees", "up to $0.00"],
      ["Must include", "hotspot"],
      ["Must not change", "port_out"],
    ]);
    const [bare] = mandateCards([proposed("m1", { max_monthly_price_minor: null, max_term_months: null, max_one_time_fees_minor: null })], none);
    expect(bare && limitRows(bare.mandate)).toEqual([]);
  });
});
