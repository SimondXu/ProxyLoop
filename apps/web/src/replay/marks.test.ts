import { describe, expect, it } from "vitest";
import type { Ev } from "../replay";
import { timeline } from "../timeline";
import { chapters, cutoff, isEvidence, marks, mmss, runDate, runHref } from "./marks";

let seq = 0;
const ev = (type: string, actor: string, t_ms: number, payload: Ev["payload"] = {}, cause_ids: string[] = []): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms, type, actor, stream: "agent", cause_ids, payload };
};
const kinds = (events: Ev[]) => marks(events, timeline(events)).map((m) => [m.kind, m.t_ms]);

describe("marks", () => {
  it("marks the offer, the approval, the decision and the outcome, from their fixed emitters, in time order", () => {
    const events = [
      ev("chan.opened", "kernel", 1000, { lane: "cp", call: 1 }),
      ev("offer.recorded", "guard", 2000, { offer_ref: "o1", revision: 1, slots: [] }),
      ev("approval.requested", "guard", 3000, { approval_id: "a1", offer_ref: "o1", revision: 1, authority_epoch: 0 }),
      ev("approval.decided", "kernel", 4000, { approval_id: "a1", decision: "granted", by: "ui" }),
      ev("session.ended", "kernel", 9000, { reason: "completed" }),
    ];
    expect(kinds(events)).toEqual([
      ["offer", 2000],
      ["approval", 3000],
      ["decision", 4000],
      ["outcome", 9000],
    ]);
  });

  it("moves on nothing but the fixed emitters (I6): a decision or an end from another actor is no marker", () => {
    const events = [
      ev("approval.decided", "slow", 4000, { approval_id: "a1", decision: "granted", by: "ui" }),
      ev("offer.recorded", "fast.cp", 2000, { offer_ref: "o1", revision: 1, slots: [] }),
      ev("session.ended", "guard", 9000, { reason: "completed" }),
    ];
    expect(kinds(events)).toEqual([]);
  });

  it("marks a stop you sent while an approval waited at its raise, not where it was cleared", () => {
    const msg = ev("user.msg", "kernel", 5000, { text: "stop" });
    const events = [
      ev("approval.requested", "guard", 3000, { approval_id: "a1", offer_ref: "o1", revision: 1, authority_epoch: 0 }),
      msg,
      ev("authority.fence", "kernel", 5100, { op: "raised", fence_id: "f1", utt_id: msg.event_id }),
      ev("authority.fence", "kernel", 7000, { op: "cleared", fence_id: "f1" }),
    ];
    expect(kinds(events)).toEqual([
      ["approval", 3000],
      ["fence", 5100],
    ]);
  });
});

describe("chapters", () => {
  it("names the four chapters and leaves the ones the run never reached null", () => {
    const events = [
      ev("chan.opened", "kernel", 1000, { lane: "user" }),
      ev("chan.opened", "kernel", 1500, { lane: "cp", call: 1 }),
      ev("session.ended", "kernel", 9000, { reason: "completed" }),
    ];
    const steps = timeline(events);
    expect(chapters(steps, marks(events, steps))).toEqual([
      { name: "Call starts", t_ms: 1500 },
      { name: "Offer", t_ms: null },
      { name: "Your decision", t_ms: null },
      { name: "Outcome", t_ms: 9000 },
    ]);
  });
});

describe("chapters: your decision", () => {
  const at = (events: Ev[]) => {
    const steps = timeline(events);
    return chapters(steps, marks(events, steps)).find((c) => c.name === "Your decision")?.t_ms;
  };

  it("starts at Guard's proposed limits in a limits-only run", () => {
    expect(at([ev("mandate.proposed", "guard", 2500, { mandate: {} })])).toBe(2500);
  });

  it("starts at the earlier of the proposed limits and the approval card, and ignores a proposal from another actor", () => {
    const card = ev("approval.requested", "guard", 3000, { approval_id: "a1", offer_ref: "o1", revision: 1, authority_epoch: 0 });
    expect(at([card, ev("mandate.proposed", "guard", 4000, { mandate: {} })])).toBe(3000);
    expect(at([ev("mandate.proposed", "guard", 1000, { mandate: {} }), card])).toBe(1000);
    expect(at([ev("mandate.proposed", "slow", 1000, { mandate: {} }), card])).toBe(3000);
  });
});

describe("clock and cut-off", () => {
  it.each([
    [0, "00:00"],
    [999, "00:00"],
    [192_000, "03:12"],
    [340_500, "05:40"],
  ])("mmss(%i) is %s", (ms, text) => expect(mmss(ms)).toBe(text));

  it("cuts at the latest event time at or before t", () => {
    const times = [0, 10, 10, 30];
    expect(cutoff(times, -1)).toBe(-1);
    expect(cutoff(times, 0)).toBe(0);
    expect(cutoff(times, 29)).toBe(10);
    expect(cutoff(times, 30)).toBe(30);
    expect(cutoff(times, 1e9)).toBe(30);
    expect(cutoff([], 5)).toBe(-1);
  });
});

describe("library rows", () => {
  it("reads the date from a kernel run id only", () => {
    expect(runDate("20260927T085615Z-aef83b")).toBe("27 Sep 2026, 08:56 UTC");
    expect(runDate("heldout-split-test")).toBeNull();
    expect(runDate("20261327T085615Z-aef83b")).toBeNull();
  });

  it("chips evidence stages, not runs/ or another root", () => {
    expect([isEvidence("s0"), isEvidence("s12"), isEvidence("runs"), isEvidence("wiring")]).toEqual([true, true, false, false]);
  });

  it("links to ?run= and keeps the view", () => {
    expect(runHref("", "a b")).toBe("?run=a+b");
    expect(runHref("?view=engineer", "r1")).toBe("?view=engineer&run=r1");
  });
});
