import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { indexEvents, laneOf, modelLabel, parseJsonl, shasOf, summary, type Ev } from "./replay";

const fixtures = fileURLToPath(new URL("../../../tests/web/fixtures", import.meta.url));
const run = join(fixtures, readdirSync(fixtures)[0] ?? "");
const events = parseJsonl<Ev>(readFileSync(join(run, "events.jsonl"), "utf-8"));

const ev = (type: string, actor: string, payload: Ev["payload"] = {}, extra: Partial<Ev> = {}): Ev => ({
  seq: 0,
  event_id: `r:${type}`,
  t_ms: 0,
  type,
  actor,
  stream: actor.startsWith("world.") ? "world" : "agent",
  cause_ids: [],
  payload,
  ...extra,
});

describe("laneOf", () => {
  it.each([
    [ev("user.msg", "kernel", { text: "hi" }), "user"],
    [ev("utt.delivered", "kernel", { lane: "user" }), "user"],
    [ev("utt.delivered", "kernel", { lane: "cp" }), "rep"],
    [ev("utt.final", "kernel", { lane: "cp", speaker: "partner" }), "rep"],
    [ev("utt.final", "kernel", { lane: "cp", speaker: "agent" }), "fast_c"],
    [ev("fast.sentence", "fast.user", { lane: "user" }), "fast_u"],
    [ev("fast.turn", "fast.cp", { lane: "cp" }), "fast_c"],
    [ev("fast.cancelled", "fast.cp", {}), "fast_c"],
    [ev("s2f.voiced", "fast.user", {}), "fast_u"],
    [ev("llm.call", "fast.cp", { role: "fast_cp" }), "fast_c"],
    [ev("llm.call", "slow", { role: "slow" }), "slow"],
    [ev("f2s.msg", "fast.cp", { lane: "cp" }), "slow"],
    [ev("s2f.msg", "guard", { lane: "user" }), "slow"],
    [ev("slow.tool", "slow", {}), "slow"],
    [ev("declass.denied", "guard", {}), "guard"],
    [ev("speak.released", "kernel", { lane: "cp" }), "guard"],
    [ev("approval.post", "ui", {}), "guard"],
    [ev("chan.strike", "kernel", { lane: "cp" }), "rep"],
    [ev("rep.ear", "world.ear", {}), "world"],
    [ev("llm.call", "world.mouth", {}), "world"],
    [ev("session.started", "kernel", {}, { stream: "ops" }), null],
    [ev("spend.charged", "kernel", {}, { stream: "ops" }), null],
  ])("%# %o", (e, lane) => expect(laneOf(e)).toBe(lane));

  it("places every agent-stream event of the fixture in a lane", () => {
    expect(events.filter((e) => e.stream === "agent" && laneOf(e) === null).map((e) => e.type)).toEqual([]);
  });
});

describe("modelLabel", () => {
  const index = indexEvents(events);

  it("follows sentence → turn → call_id → llm.call on the fixture", () => {
    const sentences = events.filter((e) => e.type === "fast.sentence");
    expect(sentences.length).toBeGreaterThan(1);
    for (const s of sentences) {
      const role = s.payload.lane === "user" ? "fast_user" : "fast_cp";
      expect(modelLabel(s, index)).toEqual({ model: `${role}-fake`, adapter: "test_fake" });
    }
  });

  it("says unknown when the chain is broken, never a guess", () => {
    const orphan = ev("fast.sentence", "fast.cp", { lane: "cp" }, { cause_ids: ["nope"] });
    expect(modelLabel(orphan, index)).toEqual({ model: "unknown", adapter: "unknown" });
    const turn = ev("fast.turn", "fast.cp", { call_id: "missing" }, { event_id: "t" });
    const s = ev("fast.sentence", "fast.cp", {}, { cause_ids: ["t"] });
    expect(modelLabel(s, indexEvents([turn, s]))).toEqual({ model: "unknown", adapter: "unknown" });
  });
});

describe("cards", () => {
  it("points llm.call and fast.request at their prompts.jsonl shas", () => {
    const [call] = events.filter((e) => e.type === "llm.call");
    expect(call && shasOf(call).map((s) => s.label)).toEqual(["prompt", "response"]);
    const [request] = events.filter((e) => e.type === "fast.request");
    expect(request && shasOf(request).map((s) => s.label)).toEqual(["view", "prompt"]);
    expect(shasOf(ev("user.msg", "kernel", { prompt_sha: "x" }))).toEqual([]);
  });

  it("summarises what was heard, returned or relayed", () => {
    expect(summary(ev("utt.delivered", "kernel", { text_heard: "Hi", interrupted: true }))).toBe("Hi [interrupted]");
    expect(summary(ev("slow.tool", "slow", { name: "act", result_text: "ok" }))).toBe("act: ok");
    expect(summary(ev("f2s.msg", "fast.cp", { type: "CP_UPDATE", facts: [["price", "75"]], text: "" }))).toBe(
      "CP_UPDATE · price=75",
    );
    expect(summary(ev("declass.denied", "guard", { violations: ["a", "b"] }))).toBe("a; b");
  });
});
