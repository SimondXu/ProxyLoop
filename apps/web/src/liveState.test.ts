import { afterEach, describe, expect, it, vi } from "vitest";
import { acceptFrame, closed, laneModels, parseEvent, start, START, unechoed, type Stream } from "./liveState";
import { CLOSE, csrfToken, entry, pageMode, paths, postApproval, postRep } from "./liveApi";
import type { Ev } from "./replay";
import { parseRepFrame, type RepFrame } from "./rep";

const line = (seq: number, type = "fast.sentence") => JSON.stringify({ seq, type, payload: {} });
const feed = (frames: string[]) => frames.reduce((s: Stream, f) => acceptFrame(s, parseEvent(f)), START);

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

  it("holds the rep stream to the same dense seq: duplicates dropped, a gap stops it", () => {
    const rep = (seqs: number[]) =>
      seqs.reduce((s: Stream<RepFrame>, seq) => acceptFrame(s, parseRepFrame(line(seq, "utt.final"))), start<RepFrame>());
    expect(rep([0, 1, 1, 2]).events.map((e) => e.seq)).toEqual([0, 1, 2]);
    expect(rep([0, 2])).toMatchObject({ phase: "error", message: "seq gap: expected 1, got 2" });
    expect(rep([3]).phase).toBe("error");
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

  const lanes = (models: Record<string, [string, string]>) =>
    Object.fromEntries(laneModels(started(models)).map((l) => [l.title, { options: l.options, running: l.running, placeholder: l.placeholder }]));

  it("offers only the lane's own real_http models: Fast from the fast roles, Slow from slow, never a world role", () => {
    expect(
      lanes({
        fast_user: ["real_http", "qwen3.5-9b"],
        fast_cp: ["real_http", "qwen3.5-9b-lora"],
        slow: ["real_http", "claude-sonnet-5"],
        ear: ["real_http", "gemini-3.8-flash"],
        mouth: ["baseline", "fsm"],
        simuser: ["recorded_replay", "sim-rec"],
      }),
    ).toEqual({
      "Fast-U": { options: ["qwen3.5-9b", "qwen3.5-9b-lora"], running: "qwen3.5-9b", placeholder: null },
      "Fast-C": { options: ["qwen3.5-9b", "qwen3.5-9b-lora"], running: "qwen3.5-9b-lora", placeholder: null },
      Slow: { options: ["claude-sonnet-5"], running: "claude-sonnet-5", placeholder: null },
    });
  });

  it("never shows a lane a model it is not running: a non-real_http lane gets a disabled placeholder", () => {
    const m = lanes({ fast_user: ["real_http", "qwen3.5-9b"], fast_cp: ["test_fake", "fast_cp-fake"], slow: ["baseline", "fsm"] });
    expect(m["Fast-C"]).toEqual({ options: [], running: null, placeholder: "fast_cp-fake (test_fake): not selectable" });
    expect(m.Slow).toEqual({ options: [], running: null, placeholder: "fsm (baseline): not selectable" });
    expect(m["Fast-U"]).toEqual({ options: ["qwen3.5-9b"], running: "qwen3.5-9b", placeholder: null });
    expect(laneModels([]).map((l) => l.placeholder)).toEqual(["no model: not selectable", "no model: not selectable", "no model: not selectable"]);
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

describe("liveApi posts", () => {
  afterEach(() => vi.unstubAllGlobals());
  const card = { approval_id: "a1", terms_hash: "th", authority_epoch: 2 };

  it("returns a bad-cookie error, never throws, when the CSRF cookie cannot be decoded", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("document", { cookie: "pl_csrf=%E0%A4%A; pl_rep_csrf=%" });
    await expect(postApproval("c", card, "granted")).resolves.toEqual({ ok: false, status: 0, error: "bad pl_csrf cookie" });
    await expect(postRep("c", "hi")).resolves.toEqual({ ok: false, status: 0, error: "bad pl_rep_csrf cookie" });
    expect(fetch).not.toHaveBeenCalled();
  });
});
