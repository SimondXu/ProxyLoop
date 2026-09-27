import { describe, expect, it } from "vitest";
import { acceptFrame, closed, parseEvent, realHttpModels, START, unechoed, type Stream } from "./liveState";
import { CLOSE, csrfToken, entry, pageMode, paths } from "./liveApi";
import type { Ev } from "./replay";

const line = (seq: number, type = "fast.sentence") => JSON.stringify({ seq, type, payload: {} });
const feed = (frames: string[], dense = true) =>
  frames.reduce((s: Stream, f) => acceptFrame(s, parseEvent(f), dense), START);

describe("the live event stream", () => {
  it("appends dense frames and drops duplicates from a reconnect overlap", () => {
    const s = feed([line(0), line(1), line(1), line(0), line(2)]);
    expect(s.events.map((e) => e.seq)).toEqual([0, 1, 2]);
    expect(s.next).toBe(3);
    expect(s.phase).toBe("connecting");
  });

  it("stops with a visible error on a gap or a bad line, and accepts nothing after", () => {
    const gap = feed([line(0), line(2), line(1)]);
    expect([gap.phase, gap.message, gap.events.length]).toEqual(["error", "seq gap: expected 1, got 2", 1]);
    expect(feed([line(0), "{oops"]).message).toMatch(/^bad frame after seq 0/);
    expect(feed(["{}"]).phase).toBe("error");
    expect(feed([JSON.stringify({ seq: 0, type: "user.msg" })]).message).toMatch(/no seq, type or payload$/);
  });

  it("lets the rep's filtered stream skip seqs, but never go back", () => {
    const s = feed([line(3), line(9), line(5)], false);
    expect(s.events.map((e) => e.seq)).toEqual([3, 9]);
    expect(s.phase).toBe("connecting");
  });

  it("reads the close codes and shows the reason", () => {
    const at = "/live/r";
    expect(closed(START, 1000, "session.ended", at)).toMatchObject({ phase: "ended", message: "stream ended (1000 session.ended)" });
    expect(closed(START, 4404, "", at)).toMatchObject({ phase: "error", message: "unknown run (4404)" });
    expect(closed(START, 1011, "gap at 7", at).phase).toBe("error");
    expect(closed(START, 1006, "", at)).toMatchObject({ phase: "closed", message: "disconnected (1006)" });
    const failed = feed(["{oops"]);
    expect(closed(failed, 1000, "", at)).toBe(failed);
  });

  it("says 4403 is not authorised and names the role's entry; only 'closed' offers a reconnect", () => {
    expect(CLOSE.forbidden).toBe(4403);
    expect(closed(START, 4403, "origin", entry("live", "r 1"))).toMatchObject({
      phase: "error",
      message: "not authorised (4403 origin): open /live/r%201 from this origin",
    });
    expect(closed(START, 4403, "", entry("rep", "r1")).message).toBe("not authorised (4403): open /rep/r1 from this origin");
  });
});

describe("model dropdown options", () => {
  const started = (models: Record<string, [string, string]>): Ev[] => [
    {
      run_id: "r", seq: 0, event_id: "r:0", t_ms: 0, type: "session.started", actor: "kernel", stream: "ops", cause_ids: [],
      payload: { models: Object.fromEntries(Object.entries(models).map(([role, [kind, model_id]]) => [role, { ref: { kind, model_id } }])) },
    },
  ];

  it("lists only real_http models, never test_fake, recorded_replay or baseline", () => {
    const m = realHttpModels(
      started({
        fast_user: ["real_http", "qwen3.5-9b"],
        fast_cp: ["test_fake", "fast_cp-fake"],
        slow: ["real_http", "claude-sonnet-5"],
        ear: ["recorded_replay", "ear-rec"],
        mouth: ["baseline", "fsm"],
        simuser: ["real_http", "qwen3.5-9b"],
      }),
    );
    expect(m.options).toEqual(["qwen3.5-9b", "claude-sonnet-5"]);
    expect(m.configured).toEqual({ fast_user: "qwen3.5-9b", slow: "claude-sonnet-5", simuser: "qwen3.5-9b" });
  });

  it("has no options without a real_http model or a session.started", () => {
    expect(realHttpModels(started({ fast_user: ["test_fake", "x"], slow: ["baseline", "fsm"] })).options).toEqual([]);
    expect(realHttpModels([]).options).toEqual([]);
  });
});

describe("pending messages", () => {
  it("clears a sent text only when its event arrives, one echo per send", () => {
    const sent = [
      { text: "stop", after: 5 },
      { text: "stop", after: 5 },
      { text: "hi", after: 9 },
    ];
    expect(unechoed(sent, [{ seq: 3, text: "stop" }])).toEqual(sent);
    expect(unechoed(sent, [{ seq: 6, text: "stop" }, { seq: 8, text: "hi" }])).toEqual([sent[1], sent[2]]);
  });
});

describe("liveApi names", () => {
  it("reads the page mode and the CSRF cookie", () => {
    expect(pageMode("?live=run-1")).toEqual({ kind: "live", id: "run-1" });
    expect(pageMode("?rep=run-1&live=run-1")).toEqual({ kind: "rep", id: "run-1" });
    expect(pageMode("")).toEqual({ kind: "replay" });
    expect(csrfToken("a=1; pl_csrf=tok%3D1; b=2", "live")).toBe("tok=1");
    expect(csrfToken("pl_csrfx=1", "live")).toBeNull();
    // Each role reads only its own CSRF cookie.
    expect(csrfToken("pl_csrf=u; pl_rep_csrf=r", "rep")).toBe("r");
    expect(csrfToken("pl_rep_csrf=r", "live")).toBeNull();
    expect(csrfToken("pl_csrf=u", "rep")).toBeNull();
    expect([paths.liveSession("c"), paths.repSession("c"), paths.repSocket("c", 7)]).toEqual([
      "/live/c",
      "/rep/c",
      "/ws/rep/c?from_seq=7",
    ]);
  });
});
