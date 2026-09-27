import { afterEach, describe, expect, it, vi } from "vitest";
import { acceptFrames, closed, parseEvent, start, START, unechoed, type Stream } from "./liveState";
import { CLOSE, csrfToken, entry, pageMode, paths, postApproval, postRep, startCase } from "./liveApi";
import { parseRepFrame, type RepFrame } from "./rep";

const M = "refused or unreachable: check the API is running, then open ";
const line = (seq: number, type = "fast.sentence") => JSON.stringify({ seq, type, payload: {} });
const feed = (frames: string[]) => frames.reduce((s: Stream, f) => acceptFrames(s, [parseEvent(f)]), START);

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
      seqs.reduce((s: Stream<RepFrame>, seq) => acceptFrames(s, [parseRepFrame(line(seq, "utt.final"))]), start<RepFrame>());
    expect(rep([0, 1, 1, 2]).events.map((e) => e.seq)).toEqual([0, 1, 2]);
    expect(rep([0, 2])).toMatchObject({ phase: "error", message: "seq gap: expected 1, got 2" });
    expect(rep([3]).phase).toBe("error");
  });

  it("takes a batch as frame-by-frame would, keeping what came before a stop", () => {
    const frames = [line(0), line(1), line(1), line(2)].map(parseEvent);
    expect(acceptFrames(START, frames)).toEqual(feed([line(0), line(1), line(1), line(2)]));
    const stopped = acceptFrames(START, [line(0), line(2), line(1)].map(parseEvent));
    expect([stopped.phase, stopped.message, stopped.events.length, stopped.next]).toEqual(["error", "seq gap: expected 1, got 2", 1, 1]);
    const dup = feed([line(0)]);
    expect(acceptFrames(dup, [parseEvent(line(0))])).toBe(dup);
  });

  it("stops /ws/live on a frame of another run (N4), like a gap", () => {
    const of = (run: unknown, seq: number) => parseEvent(JSON.stringify({ run_id: run, seq, type: "user.msg", payload: {} }));
    const ok = acceptFrames(START, [of("r1", 0), of("r1", 1)], "r1");
    expect([ok.phase, ok.next]).toEqual(["connecting", 2]);
    const foreign = acceptFrames(ok, [of("r2", 2), of("r1", 3)], "r1");
    expect([foreign.phase, foreign.message, foreign.events.length]).toEqual(["error", "frame of run r2, not r1", 2]);
    expect(acceptFrames(START, [of(undefined, 0)], "r1").message).toBe("frame of run undefined, not r1");
    expect(acceptFrames(START, [of("r2", 0)]).phase).toBe("connecting"); // /ws/rep frames carry no run_id
  });

  it("reads the close codes and shows the reason", () => {
    const at = "/live/r";
    expect(closed(START, 1000, "session.ended", at)).toMatchObject({ phase: "ended", message: "stream ended (1000 session.ended)" });
    expect(closed(START, 4404, "", at)).toMatchObject({ phase: "error", message: "unknown run (4404)" });
    expect(closed(START, 1011, "gap at 7", at).phase).toBe("error");
    expect(closed({ ...START, phase: "open" }, 1006, "", at)).toMatchObject({ phase: "closed", message: "disconnected (1006)" });
    const failed = feed(["{oops"]);
    expect(closed(failed, 1000, "", at)).toBe(failed);
  });

  it("reads a 1006 before the socket opened as refused or unreachable, and after it opened as a disconnect (N8)", () => {
    const refused = closed(START, 1006, "", entry("rep", "r1"));
    expect(refused).toMatchObject({ phase: "error", message: `${M}/rep/r1 from this origin` });
    expect(closed(START, 1006, "", entry("live", "r1")).message).toBe(`${M}/live/r1 from this origin`);
    const opened: Stream = { ...START, phase: "open" };
    expect(closed(opened, 1006, "", "/live/r1")).toMatchObject({ phase: "closed", message: "disconnected (1006)" });
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
    expect(pageMode("?start")).toEqual({ kind: "start" });
    expect(csrfToken("pl_csrf=u; pl_op_csrf=o", "start")).toBe("o");
    expect(entry("start", "")).toBe("/start");
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
    await expect(postApproval("c", card, "granted")).resolves.toEqual({ ok: false, status: 0, error: "bad pl_csrf cookie", unsent: true });
    await expect(postRep("c", "hi")).resolves.toEqual({ ok: false, status: 0, error: "bad pl_rep_csrf cookie", unsent: true });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps the API's 409 reason next to its error (serve.cases: {error, reason?})", async () => {
    const answer = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }));
    vi.stubGlobal("document", { cookie: "pl_csrf=t" });
    vi.stubGlobal("fetch", answer(409, { error: "stale", reason: "stale_epoch" }));
    await expect(postApproval("c", card, "granted")).resolves.toEqual({ ok: false, status: 409, error: "stale", reason: "stale_epoch" });
    vi.stubGlobal("fetch", answer(409, { error: "already_decided" }));
    await expect(postApproval("c", card, "granted")).resolves.toEqual({ ok: false, status: 409, error: "already_decided" });
  });

  it("starts a case with the operator's token, once, and reads the case_id or the refusal", async () => {
    const answer = (status: number, body: unknown) => vi.fn(async () => new Response(JSON.stringify(body), { status }));
    const body = { task_ref: "t", models: { slow: "s" }, rep: "sim" as const };
    vi.stubGlobal("document", { cookie: "pl_csrf=u; pl_op_csrf=op" });
    const created = answer(201, { case_id: "run-1" });
    vi.stubGlobal("fetch", created);
    await expect(startCase(body)).resolves.toEqual({ ok: true, caseId: "run-1" });
    expect(created).toHaveBeenCalledTimes(1);
    expect(created).toHaveBeenCalledWith("/api/cases", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": "op" },
      body: JSON.stringify(body),
    });
    vi.stubGlobal("fetch", answer(409, { error: "start", reason: "busy" }));
    await expect(startCase(body)).resolves.toEqual({ ok: false, status: 409, error: "start", reason: "busy" });
    vi.stubGlobal("document", { cookie: "pl_csrf=u" });
    await expect(startCase(body)).resolves.toEqual({ ok: false, status: 0, error: "no pl_op_csrf cookie: open /start first", unsent: true });
    vi.stubGlobal("document", { cookie: "pl_op_csrf=op" });
    vi.stubGlobal("fetch", answer(201, {}));
    await expect(startCase(body)).resolves.toEqual({ ok: false, status: 0, error: "no case_id in the answer" });
  });
});
