import { describe, expect, it } from "vitest";
import { conversation } from "./conversation";
import type { Ev } from "./replay";
import { fresh, modelOptions, speakItems } from "./voice";

let seq = 0;
const ev = (type: string, payload: Ev["payload"]): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor: "kernel", stream: "agent", cause_ids: [], payload };
};
const said = (heard: string, generated = heard) => ev("utt.delivered", { lane: "cp", utt_id: "u", text_generated: generated, text_heard: heard, interrupted: generated !== heard });
const rep = (text: string) => ev("utt.final", { lane: "cp", speaker: "partner", utt_id: "p", text });

describe("the call's spoken lines", () => {
  const events = [
    ev("chan.opened", { lane: "cp" }),
    ev("utt.delivered", { lane: "user", text_generated: "chat", text_heard: "chat", interrupted: false }),
    said("We accept", "We accept the offer of $70."),
    rep("Thanks, one moment."),
    ev("utt.final", { lane: "cp", speaker: "agent", utt_id: "x", text: "agent echo" }),
    ev("chan.closed", { lane: "cp" }),
  ];

  it("are the agent's text_heard (never text_generated) and the rep's utt.final, in order", () => {
    const items = speakItems(conversation(events).call);
    expect(items.map((i) => [i.speaker, i.text])).toEqual([
      ["agent", "We accept"],
      ["rep", "Thanks, one moment."],
    ]);
    expect(JSON.stringify(items)).not.toContain("$70");
  });

  it("are yielded once: a re-run over the same events, or a longer stream, yields only the new ones", () => {
    const seen = new Set<string>();
    expect(fresh(speakItems(conversation(events).call), seen)).toHaveLength(2);
    expect(fresh(speakItems(conversation(events).call), seen)).toEqual([]);
    const more = [...events, rep("Anything else?")];
    expect(fresh(speakItems(conversation(more).call), seen).map((i) => i.text)).toEqual(["Anything else?"]);
  });
});

describe("modelOptions", () => {
  it("never runs q8 on webgpu (it garbles the speech)", () => {
    expect(modelOptions(true)).toEqual({ device: "webgpu", dtype: "fp32" });
    expect(modelOptions(false)).toEqual({ device: "wasm", dtype: "q8" });
  });
});
