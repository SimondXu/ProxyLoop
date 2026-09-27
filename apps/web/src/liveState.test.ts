import { describe, expect, it } from "vitest";
import { acceptFrame, closed, realHttpModels, START, unechoed, type Stream } from "./liveState";
import { csrfToken, pageMode } from "./liveApi";
import type { Ev } from "./replay";

const line = (seq: number, type = "fast.sentence") => JSON.stringify({ seq, type, payload: {} });
const feed = (frames: string[], dense = true) => frames.reduce((s: Stream, f) => acceptFrame(s, f, dense), START);

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
  });

  it("lets the rep's filtered stream skip seqs, but never go back", () => {
    const s = feed([line(3), line(9), line(5)], false);
    expect(s.events.map((e) => e.seq)).toEqual([3, 9]);
    expect(s.phase).toBe("connecting");
  });

  it("reads the close codes and shows the reason", () => {
    expect(closed(START, 1000, "session.ended")).toMatchObject({ phase: "ended", message: "stream ended (1000 session.ended)" });
    expect(closed(START, 4404, "")).toMatchObject({ phase: "error", message: "unknown run (4404)" });
    expect(closed(START, 1011, "gap at 7").phase).toBe("error");
    expect(closed(START, 1006, "")).toMatchObject({ phase: "closed", message: "disconnected (1006)" });
    const failed = feed(["{oops"]);
    expect(closed(failed, 1000, "")).toBe(failed);
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
    expect(csrfToken("a=1; pl_csrf=tok%3D1; b=2")).toBe("tok=1");
    expect(csrfToken("pl_csrfx=1")).toBeNull();
  });
});
