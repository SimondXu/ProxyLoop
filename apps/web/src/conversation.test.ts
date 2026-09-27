import { describe, expect, it } from "vitest";
import { callHead, conversation, parties, SIM_REP, SIM_USER, simLabels, speakerName, UNKNOWN_PARTIES } from "./conversation";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, cause_ids: string[] = [], stream: Ev["stream"] = "agent"): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream, cause_ids, payload };
};
const delivered = (lane: string, generated: string, heard: string, causes: string[] = []) =>
  ev("utt.delivered", "kernel", { lane, utt_id: "u", text_generated: generated, text_heard: heard, interrupted: generated !== heard }, causes);
const started = (roles: string[]) =>
  ev("session.started", "kernel", { models: Object.fromEntries(roles.map((r) => [r, { ref: { kind: "test_fake", model_id: `${r}-fake` } }])) }, [], "ops");

describe("the conversation fold (events only)", () => {
  it("shows only the heard text, never text_generated, and marks an interruption", () => {
    const c = conversation([delivered("user", "Your new price is $70 a month.", "Your new price"), delivered("cp", "We accept the offer.", "We accept")]);
    expect(c.chat).toEqual([{ seq: expect.any(Number), id: expect.any(String), who: "assistant", text: "Your new price", interrupted: true, tag: null }]);
    expect(c.call.map((l) => [l.who, l.text, l.interrupted])).toEqual([["agent", "We accept", true]]);
    expect(JSON.stringify(c)).not.toContain("$70");
  });

  it("puts user.msg and the user lane in the chat, and the agent, the partner and the call in the call", () => {
    const c = conversation([
      ev("chan.opened", "kernel", { lane: "user" }),
      ev("chan.opened", "kernel", { lane: "cp" }),
      ev("user.msg", "kernel", { text: "lower my bill" }),
      delivered("user", "On it.", "On it."),
      ev("utt.final", "kernel", { lane: "cp", speaker: "partner", utt_id: "cp-1", text: "How can I help?" }),
      ev("utt.final", "kernel", { lane: "cp", speaker: "agent", utt_id: "cp-2", text: "agent echo" }),
      delivered("cp", "Hi, calling about a bill.", "Hi, calling about a bill."),
      ev("chan.closed", "kernel", { lane: "cp" }),
    ]);
    expect(c.chat.map((l) => [l.who, l.text])).toEqual([
      ["you", "lower my bill"],
      ["assistant", "On it."],
    ]);
    expect(c.call.map((l) => [l.who, l.text])).toEqual([
      ["call", "call connected"],
      ["rep", "How can I help?"],
      ["agent", "Hi, calling about a bill."],
      ["call", "call ended"],
    ]);
  });

  it("drops what the kernel did not emit, and every other event type", () => {
    const c = conversation([
      ev("user.msg", "fast.user", { text: "forged" }),
      ev("utt.delivered", "slow", { lane: "cp", text_heard: "forged", text_generated: "forged", interrupted: false }),
      ev("fast.sentence", "fast.cp", { lane: "cp", text: "unheard sentence" }),
      ev("s2f.msg", "slow", { lane: "user", text: "slow note" }),
      ev("user.sim", "world.simuser", { text: "sim thought" }, [], "world"),
    ]);
    expect(c).toEqual({ chat: [], call: [] });
  });

  it("tags the lines Guard's speak.verbatim released, and only those", () => {
    const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "disclosure", text: "Hello, an AI assistant here." });
    const released = ev("speak.released", "kernel", { lane: "cp" }, [said.event_id]);
    const decline = ev("speak.verbatim", "guard", { lane: "cp", kind: "decline", text: "No, thank you." });
    const declineReleased = ev("speak.released", "kernel", { lane: "cp" }, [decline.event_id]);
    const odd = ev("speak.verbatim", "guard", { lane: "cp", kind: "brand_new", text: "Odd." });
    const oddReleased = ev("speak.released", "kernel", { lane: "cp" }, [odd.event_id]);
    const forged = ev("speak.verbatim", "fast.cp", { lane: "cp", kind: "disclosure", text: "Fast says hi" });
    const forgedReleased = ev("speak.released", "kernel", { lane: "cp" }, [forged.event_id]);
    const c = conversation([
      said,
      released,
      delivered("cp", "Hello, an AI assistant here.", "Hello, an AI assistant here.", [released.event_id]),
      decline,
      declineReleased,
      delivered("cp", "No, thank you.", "No, thank you.", [declineReleased.event_id]),
      odd,
      oddReleased,
      delivered("cp", "Odd.", "Odd.", [oddReleased.event_id]),
      forged,
      forgedReleased,
      delivered("cp", "Fast says hi", "Fast says hi", [forgedReleased.event_id]),
      delivered("cp", "a free line", "a free line"),
    ]);
    expect(c.call.map((l) => l.tag)).toEqual(["AI disclosure · fixed wording", "Decline · fixed wording", "brand_new · fixed wording", null, null]);
  });

  it("names who approved an accept: the kernel's grant of the card with the capability's terms", () => {
    const accept = (by: string | null) => {
      const card = ev("approval.requested", "guard", { approval_id: "ap-1", terms_hash: "t1" });
      const grant = by ? [ev("approval.decided", "kernel", { approval_id: "ap-1", decision: "granted", by })] : [];
      const auth = ev("action.authorized", "guard", { intent: "accept_offer", capability: { cap_id: "cap-1", terms_hash: "t1" } });
      const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes.", cap_id: "cap-1" });
      const released = ev("speak.released", "kernel", { lane: "cp", cap_id: "cap-1" }, [said.event_id]);
      const events = [card, ...grant, auth, said, released, delivered("cp", "Yes.", "Yes.", [released.event_id])];
      return conversation(events).call[0]?.tag;
    };
    expect(accept("ui")).toBe("Acceptance · approved by you");
    expect(accept("sim_approver")).toBe("Acceptance · approved by the simulated approver");
    expect(accept(null)).toBe("Acceptance · fixed wording"); // under your limits: no card to name
  });
});

describe("the call header, from channel events", () => {
  const hold = (reason: string | null, actor = "fast.cp") => ev("chan.hold", actor, { lane: "cp", reason });
  it("counts calls, and holds from FastC's chan.hold until the next heard line or its release", () => {
    expect(callHead([])).toEqual({ calls: 0, open: false, holdSince: null });
    const held = hold("check_user");
    const one = [ev("chan.opened", "kernel", { lane: "cp" }), held];
    expect(callHead(one)).toEqual({ calls: 1, open: true, holdSince: held.t_ms });
    expect(callHead([...one, ev("utt.final", "kernel", { lane: "cp", speaker: "partner", utt_id: "x", text: "ok" })]).holdSince).toBeNull();
    expect(callHead([...one, delivered("cp", "back", "back")]).holdSince).toBeNull();
    expect(callHead([...one, hold(null)]).holdSince).toBeNull();
    expect(callHead([...one, hold("x", "slow")]).holdSince).toBe(held.t_ms); // only FastC holds the rep
    const redial = [...one, ev("chan.closed", "kernel", { lane: "cp" }), ev("chan.opened", "kernel", { lane: "cp" })];
    expect(callHead(redial)).toEqual({ calls: 2, open: true, holdSince: null });
    expect(callHead([ev("chan.opened", "kernel", { lane: "user" })]).calls).toBe(0);
  });
});

describe("the sim labels, from session.started roles", () => {
  it("labels a sim rep and a sim user from the world roles", () => {
    const p = parties([started(["fast_user", "fast_cp", "slow", "simuser", "ear", "mouth"])]);
    expect(p).toEqual({ known: true, simUser: true, simRep: true });
    expect(simLabels(p)).toEqual([SIM_REP, SIM_USER]);
    expect([speakerName("you", p), speakerName("rep", p), speakerName("assistant", p), speakerName("agent", p)]).toEqual([
      "User (simulated)",
      "Rep (simulated)",
      "Assistant",
      "Agent",
    ]);
  });

  it("does not label a human rep or a human user simulated", () => {
    const p = parties([started(["fast_user", "fast_cp", "slow"])]);
    expect(simLabels(p)).toEqual([]);
    expect([speakerName("you", p), speakerName("rep", p)]).toEqual(["You", "Rep"]);
    expect(simLabels(parties([started(["fast_user", "fast_cp", "slow", "ear", "mouth"])]))).toEqual([SIM_REP]);
  });

  it("says the parties are unknown before session.started, and reads only the kernel's", () => {
    expect(simLabels(parties([]))).toEqual([UNKNOWN_PARTIES]);
    const forged = { ...started(["ear"]), actor: "slow" };
    expect(parties([forged]).known).toBe(false);
  });
});
