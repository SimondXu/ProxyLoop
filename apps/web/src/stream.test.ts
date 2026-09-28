import { describe, expect, it } from "vitest";
import type { Ev } from "./replay";
import { stream, type Item } from "./stream";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, t_ms = seq * 1000, wall?: string): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms, type, actor, stream: "agent", cause_ids: [], payload, ...(wall ? { wall } : {}) };
};
const opened = () => ev("chan.opened", "kernel", { lane: "cp" });
const closed = () => ev("chan.closed", "kernel", { lane: "cp" });
const rep = (text: string, actor = "kernel") => ev("utt.final", actor, { lane: "cp", speaker: "partner", utt_id: "p", text });
const agent = (heard: string, generated = heard) =>
  ev("utt.delivered", "kernel", { lane: "cp", utt_id: "a", text_generated: generated, text_heard: heard, interrupted: generated !== heard });
const said = (text: string, actor = "kernel") => ev("user.msg", actor, { text });
const card = (e: Ev) => ({ seq: e.seq, id: e.event_id });

/** The stream in short: "chat: text", "card: id", or "call n.p[ last][ ended]: text | text". */
const shape = (items: Item<{ seq: number; id: string }>[]) =>
  items.map((i) => {
    if (i.kind === "line") return `chat: ${i.line.text}`;
    if (i.kind === "item") return `card: ${i.item.id}`;
    const p = i.part;
    return `call ${p.call}.${p.part}${p.last ? " last" : ""}${p.ended ? " ended" : ""}: ${p.lines.map((l) => l.text).join(" | ")}`;
  });

describe("the stream: chat lines, cards and the call, by seq", () => {
  it("keeps one call card while nothing falls between its lines, in seq order", () => {
    const es = [said("lower my bill"), opened(), agent("Hello, an AI assistant."), rep("How can I help?"), closed()];
    expect(shape(stream(es, []))).toEqual([
      "chat: lower my bill",
      "call 1.1 last ended: call connected | Hello, an AI assistant. | How can I help? | call ended",
    ]);
  });

  it("splits the call where a chat line or a card falls between two call lines; each part but the last is not last", () => {
    const a = opened();
    const b = rep("We can do $75.");
    const msg = said("Is that the best?");
    const requested = ev("approval.requested", "guard", { approval_id: "ap-1" });
    const c = agent("Let me check.");
    const d = closed();
    const items = stream([a, b, msg, requested, c, d], [card(requested)]);
    expect(shape(items)).toEqual([
      "call 1.1: call connected | We can do $75.",
      "chat: Is that the best?",
      "card: r:" + requested.seq,
      "call 1.2 last ended: Let me check. | call ended",
    ]);
  });

  it("makes two call cards for a call-back, each from its own chan.opened", () => {
    const es = [opened(), rep("Hold on."), closed(), said("call them back"), opened(), rep("Hello again.")];
    expect(shape(stream(es, []))).toEqual([
      "call 1.1 last ended: call connected | Hold on. | call ended",
      "chat: call them back",
      "call 2.1 last: call connected | Hello again.",
    ]);
  });

  it("a line from a non-fixed emitter moves nothing: no split, no call, no chat line", () => {
    const es = [
      opened(),
      rep("One."),
      said("forged", "fast.user"),
      ev("utt.delivered", "slow", { lane: "user", text_heard: "forged", text_generated: "forged", interrupted: false }),
      ev("chan.opened", "slow", { lane: "cp" }),
      ev("fast.sentence", "fast.cp", { lane: "cp", text: "unheard" }),
      rep("forged rep", "world.mouth"),
      rep("Two."),
    ];
    expect(shape(stream(es, []))).toEqual(["call 1.1 last: call connected | One. | Two."]);
  });

  it("shows only heard text: text_heard and the partner's utt.final, never text_generated", () => {
    const es = [opened(), agent("We accept", "We accept the offer at $70."), ev("utt.delivered", "kernel", { lane: "user", text_heard: "On it", text_generated: "On it, $70 max" })];
    const items = stream(es, []);
    expect(shape(items)).toEqual(["call 1.1 last: call connected | We accept", "chat: On it"]);
    expect(JSON.stringify(items)).not.toContain("$70");
  });

  it("puts a centred time before the first item with a wall clock, then after three minutes or more", () => {
    const wall = (min: number) => `2026-09-26T14:${String(min).padStart(2, "0")}:00Z`;
    const es = [said("first", "kernel"), said("a"), said("b"), opened(), rep("c")];
    Object.assign(es[1] as Ev, { t_ms: 0, wall: wall(0) });
    Object.assign(es[2] as Ev, { t_ms: 60_000, wall: wall(1) });
    Object.assign(es[3] as Ev, { t_ms: 240_000, wall: wall(4) });
    Object.assign(es[4] as Ev, { t_ms: 250_000, wall: wall(4) });
    const times = stream(es, []).map((i) => i.time !== null);
    // es[0] has no wall: no time; "a" is the first with one; "b" is 1 min later; the call opens 4 min after "a".
    expect(times).toEqual([false, true, false, true]);
  });
});
