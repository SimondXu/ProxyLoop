import { describe, expect, it } from "vitest";
import { receipts } from "./fenceTicks";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream: "agent", cause_ids: [], payload };
};
const fence = (op: string, utt: string, id = "fence-1", actor = "kernel") => ev("authority.fence", actor, { op, fence_id: id, utt_id: utt });

describe("the chat's read receipts, from authority.fence on each user.msg", () => {
  it("is pausing while the message's fence is raised, and read once it clears", () => {
    const msg = ev("user.msg", "kernel", { text: "stop" });
    expect(receipts([msg]).get(msg.event_id)).toBeUndefined(); // no fence event: no receipt
    expect(receipts([msg, fence("raised", msg.event_id)]).get(msg.event_id)).toBe("pausing");
    expect(receipts([msg, fence("raised", msg.event_id), fence("cleared", msg.event_id)]).get(msg.event_id)).toBe("read");
  });

  it("keeps each message's own fences, and reads only the fixed emitters'", () => {
    const a = ev("user.msg", "kernel", { text: "a" });
    const b = ev("user.msg", "kernel", { text: "b" });
    const r = receipts([a, b, fence("raised", a.event_id, "f1"), fence("raised", b.event_id, "f2"), fence("cleared", a.event_id, "f1")]);
    expect([r.get(a.event_id), r.get(b.event_id)]).toEqual(["read", "pausing"]);
    expect(receipts([a, fence("raised", a.event_id, "f1", "fast.user")]).size).toBe(0);
  });
});
