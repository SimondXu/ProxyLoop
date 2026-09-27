import { describe, expect, it } from "vitest";
import type { Ev } from "./replay";
import { parseRepFrame, repLine, type RepFrame } from "./rep";

// Every event type of the contract registry (ARCHITECTURE §4.2).
// tests/web/test_rep_allowlist.py keeps this list equal to EVENT_TYPES.
const ALL_TYPES = [
  "session.started", "session.ended", "spend.charged", "parity.checked", "attest.recorded",
  "llm.call",
  "user.msg", "utt.final", "utt.delivered", "chan.opened", "chan.closed", "chan.hold", "chan.strike", "chan.barge_in",
  "fast.request", "fast.turn", "fast.sentence", "fast.cancelled",
  "f2s.msg", "s2f.msg", "s2f.voiced",
  "slow.step.started", "slow.step.completed", "slow.tool",
  "summary.updated", "declass.denied", "fact.recorded", "offer.recorded", "readback.updated",
  "approval.post", "authority.fence", "authority.epoch", "mandate.proposed", "mandate.decided",
  "approval.requested", "approval.decided", "action.authorized", "action.denied",
  "speak.verbatim", "speak.released", "speak.revoked", "screen.redacted", "evidence.recorded",
  "status.changed", "completion.decided",
  "rep.ear", "rep.policy", "rep.mouth", "rep.commit_heard", "ledger.write", "user.sim",
];

const SECRET = "PRIVATE floor is $60";
const STREAM: Record<string, Ev["stream"]> = { session: "ops", spend: "ops", parity: "ops", attest: "ops", rep: "world", ledger: "world", user: "agent" };
const ev = (type: string, actor: string, payload: Ev["payload"], stream: Ev["stream"] = "agent"): Ev => ({
  run_id: "r", seq: 7, event_id: "r:7", t_ms: 0, type, actor, stream, cause_ids: [], payload,
});
const streamOf = (type: string) => (type === "user.sim" ? "world" : STREAM[type.split(".")[0] ?? ""] ?? "agent");
// Every type on every lane and speaker, each payload carrying private text.
const everything = ALL_TYPES.flatMap((type) =>
  ["user", "cp", undefined].flatMap((lane) =>
    ["partner", "agent"].map((speaker) =>
      ev(type, "kernel", { lane, speaker, scope: "private", text: SECRET, text_generated: SECRET, text_heard: "heard" }, streamOf(type)),
    ),
  ),
);

describe("repLine: the human rep's allow-list (I4)", () => {
  it("passes only cp utt.delivered, partner utt.final and cp chan.opened/closed", () => {
    const passed = everything.filter((e) => repLine(e) !== null).map((e) => `${e.type}/${e.payload.lane}/${e.payload.speaker}`);
    expect([...new Set(passed.map((p) => p.split("/").slice(0, 2).join("/")))]).toEqual([
      "utt.final/cp",
      "utt.delivered/cp",
      "chan.opened/cp",
      "chan.closed/cp",
    ]);
    expect(passed.filter((p) => p.startsWith("utt.final"))).toEqual(["utt.final/cp/partner"]);
  });

  it("shows what was heard, never what was generated or anything private", () => {
    const lines = everything.map(repLine).filter((l) => l !== null);
    expect(lines.filter((l) => l.who === "agent").map((l) => l.text)).toEqual(["heard", "heard"]);
    expect(JSON.stringify(lines.filter((l) => l.who !== "rep"))).not.toContain(SECRET);
    expect(repLine(ev("utt.delivered", "kernel", { lane: "cp", text_heard: "Hel", interrupted: true }))?.text).toBe(
      "Hel [interrupted]",
    );
  });

  it("drops the private and god-view events a live stream carries", () => {
    const privateOnes = [
      ev("summary.updated", "guard", { scope: "private", text: SECRET }),
      ev("user.msg", "kernel", { text: SECRET }),
      ev("f2s.msg", "fast.cp", { lane: "cp", text: SECRET }),
      ev("approval.requested", "guard", { readback_text: SECRET }),
      ev("fast.sentence", "fast.cp", { lane: "cp", text: SECRET }),
      ev("speak.verbatim", "guard", { lane: "cp", text: SECRET }),
      ev("rep.mouth", "world.mouth", { text: SECRET }, "world"),
      ev("llm.call", "fast.cp", { lane: "cp" }),
    ];
    expect(privateOnes.map(repLine)).toEqual(privateOnes.map(() => null));
  });

  it("accepts only the kernel as the emitter of a heard line", () => {
    expect(repLine(ev("utt.delivered", "fast.cp", { lane: "cp", text_heard: SECRET }))).toBeNull();
    expect(repLine(ev("utt.final", "world.mouth", { lane: "cp", speaker: "partner", text: "x" }, "world"))).toBeNull();
  });
});

describe("repLine on bare /ws/rep frames (no actor, no stream)", () => {
  const bare = (type: string, payload: RepFrame["payload"]): RepFrame => ({ seq: 11, t_ms: 5, type, payload });

  it("rejects bare frames of private types, even when they claim the cp lane", () => {
    for (const type of ["summary.updated", "user.msg", "f2s.msg", "approval.requested"]) {
      expect(repLine(bare(type, { lane: "cp", scope: "private", text: SECRET, readback_text: SECRET }))).toBeNull();
    }
  });

  it("passes exactly the allow-listed types on the cp lane", () => {
    const passed = ALL_TYPES.flatMap((type) =>
      ["cp", "user", undefined].flatMap((lane) =>
        repLine(bare(type, { lane, speaker: "partner", text: "t", text_heard: "h" })) ? [`${type}/${lane}`] : [],
      ),
    );
    expect(passed).toEqual(["utt.final/cp", "utt.delivered/cp", "chan.opened/cp", "chan.closed/cp"]);
    expect(repLine(bare("utt.final", { lane: "cp", speaker: "agent", text: SECRET }))).toBeNull();
  });

  it("shows only text_heard of a bare cp utt.delivered", () => {
    const line = repLine(bare("utt.delivered", { lane: "cp", text_generated: SECRET, text_heard: "Hello", interrupted: false }));
    expect(line).toEqual({ seq: 11, who: "agent", text: "Hello" });
  });

  it("parses a rebuilt frame, drops unknown fields, and still checks actor and stream when present", () => {
    const frame = parseRepFrame(JSON.stringify({ seq: 4, t_ms: 9, type: "chan.opened", payload: { lane: "cp" }, cause_ids: ["x"] }));
    expect(frame).toEqual({ seq: 4, t_ms: 9, type: "chan.opened", payload: { lane: "cp" } });
    const as = (extra: object) => parseRepFrame(JSON.stringify({ seq: 4, t_ms: 9, type: "chan.opened", payload: { lane: "cp" }, ...extra }));
    const line = (f: RepFrame | string) => (typeof f === "string" ? f : repLine(f));
    expect(line(as({ actor: "kernel", stream: "agent" }))).toMatchObject({ who: "call" });
    expect(line(as({ actor: "fast.cp" }))).toBeNull();
    expect(line(as({ stream: "world" }))).toBeNull();
    expect(parseRepFrame(JSON.stringify({ seq: 4, type: "chan.opened" }))).toBe("no seq, type or payload");
  });
});
