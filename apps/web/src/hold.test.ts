import { describe, expect, it } from "vitest";
import { holdElapsed, holdElapsedAt, mmss } from "./hold";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, t_ms: number, payload: Ev["payload"] = {}): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms, type, actor, stream: "agent", cause_ids: [], payload };
};
const opened = (t: number) => ev("chan.opened", "kernel", t, { lane: "cp" });
const hold = (t: number, reason: string | null, actor = "fast.cp") => ev("chan.hold", actor, t, { lane: "cp", reason });
const heard = (t: number) => ev("utt.final", "kernel", t, { lane: "cp", speaker: "partner", utt_id: "p", text: "Still there?" });

describe("the hold line (display only)", () => {
  it("formats elapsed ms as m:ss", () => {
    expect(mmss(0)).toBe("0:00");
    expect(mmss(59_000)).toBe("0:59");
    expect(mmss(59_999)).toBe("0:59");
    expect(mmss(60_000)).toBe("1:00");
    expect(mmss(600_000)).toBe("10:00");
  });

  it("is hidden with no hold, and when FastC's chan.hold with no reason ends it", () => {
    expect(holdElapsed([])).toBeNull();
    expect(holdElapsed([opened(0), heard(5_000)])).toBeNull();
    expect(holdElapsed([opened(0), hold(1_000, "check_user"), hold(9_000, null)])).toBeNull();
    expect(holdElapsed([opened(0), hold(1_000, "check_user"), ev("chan.closed", "kernel", 2_000, { lane: "cp" })])).toBeNull();
    expect(holdElapsed([opened(0), hold(1_000, "check_user", "slow")])).toBeNull(); // only FastC holds the rep
  });

  it("counts up from the hold that applies (the call's current one), on the events' t_ms only", () => {
    const first = [opened(0), hold(1_000, "check_user"), hold(4_000, null)];
    expect(holdElapsed([...first, hold(10_000, "decision")])).toBe(0);
    expect(holdElapsed([...first, hold(10_000, "decision"), heard(64_000)])).toBe(54_000);
    const events = [opened(0), hold(10_000, "decision"), heard(20_000)];
    expect(holdElapsed(events)).toBe(10_000);
    // Live adds the local ms since the latest event arrived, display only.
    expect(holdElapsed(events, 3_500)).toBe(13_500);
    expect(mmss(holdElapsed([opened(0), hold(0, "decision"), heard(600_000)]) ?? -1)).toBe("10:00");
  });

  it("in a replay follows the playback clock t (recorded t_ms), also between events, and only the shown events' hold", () => {
    const shown = [opened(0), hold(10_000, "decision"), heard(20_000)];
    // Between events it moves with t instead of standing at the latest event's t_ms.
    expect([20_000, 21_000, 25_500, 70_000].map((t) => mmss(holdElapsedAt(shown, t) ?? -1))).toEqual(["0:10", "0:11", "0:15", "1:00"]);
    expect(holdElapsedAt(shown, 25_500)).toBe(15_500);
    expect(holdElapsedAt(shown, 25_500)).toBe(holdElapsedAt(shown, 25_500)); // paused: the same t, the same text
    expect(holdElapsedAt([opened(0), heard(5_000)], 9_000)).toBeNull();
    expect(holdElapsedAt([...shown, hold(30_000, null)], 40_000)).toBeNull();
    expect(holdElapsedAt([opened(0), hold(10_000, "decision", "slow")], 40_000)).toBeNull();
  });
});
