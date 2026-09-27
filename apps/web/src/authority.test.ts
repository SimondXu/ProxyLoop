import { describe, expect, it } from "vitest";
import { authorityStrip, epochOf } from "./authority";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream: "agent", cause_ids: [], payload };
};
const fence = (op: string, id: string, actor = "kernel") => ev("authority.fence", actor, { op, fence_id: id, utt_id: "r:1" });
const status = (previous: string, to: string, actor = "guard") => ev("status.changed", actor, { previous, status: to });

describe("the authority strip (events only)", () => {
  it("starts empty", () => {
    expect(authorityStrip([])).toEqual({ status: null, fences: [], lastFence: null, epoch: 0, revoked: null, denied: null });
  });

  it("shows the latest status.changed and the max epoch, from the fixed emitters only", () => {
    const events = [
      status("INTAKE", "IN_CALL"),
      status("IN_CALL", "AWAITING_APPROVAL"),
      status("AWAITING_APPROVAL", "VERIFIED_COMPLETE", "fast.user"),
      ev("authority.epoch", "guard", { new: 2 }),
      ev("authority.epoch", "kernel", { new: 1 }),
      ev("authority.epoch", "slow", { new: 9 }),
    ];
    const s = authorityStrip(events);
    expect([s.status, s.epoch, epochOf(events)]).toEqual(["AWAITING_APPROVAL", 2, 2]);
  });

  it("tracks raised fences until cleared, with their ids", () => {
    expect(authorityStrip([fence("raised", "fence-1")])).toMatchObject({ fences: ["fence-1"], lastFence: { op: "raised", fence_id: "fence-1" } });
    const two = [fence("raised", "fence-1"), fence("raised", "fence-2"), fence("cleared", "fence-1")];
    expect(authorityStrip(two)).toMatchObject({ fences: ["fence-2"], lastFence: { op: "cleared", fence_id: "fence-1" } });
    expect(authorityStrip([...two, fence("cleared", "fence-2")]).fences).toEqual([]);
    expect(authorityStrip([fence("raised", "fence-9", "fast.cp")]).lastFence).toBeNull();
  });

  it("keeps the last speak.revoked and action.denied, naming who emitted them", () => {
    const events = [
      ev("speak.revoked", "kernel", { lane: "cp", reason: "stale" }),
      ev("action.denied", "guard", { intent: "accept_offer", reason: "readback_not_confirmed" }),
      ev("speak.revoked", "kernel", { lane: "cp", reason: "fence" }),
      ev("action.denied", "kernel", { intent: "approval.post", reason: "fence_raised" }),
    ];
    expect(authorityStrip(events)).toMatchObject({
      revoked: { reason: "fence", actor: "kernel" },
      denied: { intent: "approval.post", reason: "fence_raised", actor: "kernel" },
    });
  });
});
