import { describe, expect, it } from "vitest";
import { approvalCards } from "./approval";
import { mandateCards } from "./mandate";
import type { Ev } from "./replay";
import { groups, now, PAYLOAD_KEYS, planner, timeline } from "./timeline";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, causes: Ev[] = []): Ev => {
  seq += 1;
  const stream = type.startsWith("session.") ? "ops" : "agent";
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq * 1000, type, actor, stream, cause_ids: causes.map((c) => c.event_id), payload };
};

/** A generation the voice spoke and the kernel delivered (fast.sentence → utt.delivered). */
function delivery(lane: string, gen: string): Ev[] {
  const s = ev("fast.sentence", `fast.${lane}`, { lane, gen_id: gen, utt_id: `${gen}-u0`, text: "unheard" });
  return [s, ev("utt.delivered", "kernel", { lane, utt_id: `${gen}-u0`, text_generated: "g", text_heard: "h", interrupted: false }, [s])];
}
const s2f = (lane: string, type: string, msg: string, extra: Ev["payload"] = {}, actor = "guard") =>
  ev("s2f.msg", actor, { msg_id: msg, lane, type, text: lane === "user" ? "a question" : "", guide: null, approval_id: null, ...extra });
const voiced = (lane: string, msg: string, gen: string, actor = `fast.${lane}`) => ev("s2f.voiced", actor, { msg_id: msg, gen_id: gen });
function verbatim(kind: string, extra: Ev["payload"] = {}): [Ev, Ev, Ev] {
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind, text: "fixed", ...extra });
  const released = ev("speak.released", "kernel", { lane: "cp" }, [said]);
  return [said, released, ev("utt.delivered", "kernel", { lane: "cp", utt_id: `${kind}-1`, text_generated: "fixed", text_heard: "fixed", interrupted: false }, [released])];
}
const offer = (revision = 1) =>
  ev("offer.recorded", "guard", {
    offer_ref: "o1",
    revision,
    terms_hash: "h1",
    slots: [
      { field: "monthly_price", value: "7800", unit: "usd_minor" },
      { field: "term_months", value: "24", unit: "months" },
    ],
  });
const card = (id = "a1", epoch = 0) =>
  ev("approval.requested", "guard", { approval_id: id, offer_ref: "o1", revision: 1, terms_hash: "h1", readback_text: "rb", authority_epoch: epoch, expires_ms: 9e6, binding: {} });
const granted = (id: string, by = "ui") => {
  const post = ev("approval.post", by, { subject: "approval", subject_id: id, decision: "granted", subject_hash: "h1", authority_epoch: 0 });
  return [post, ev("approval.decided", "kernel", { approval_id: id, decision: "granted", by }, [post])];
};
const mandate = () => ev("mandate.proposed", "guard", { mandate_id: "m1", mandate_hash: "mh", status: "proposed", epoch: 0, max_monthly_price_minor: 6500 });
function accept(): [Ev, Ev] {
  const auth = ev("action.authorized", "guard", { intent: "accept_offer", capability: { cap_id: "c1", terms_hash: "h1", epoch: 0 } });
  return [auth, ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: "c1" })];
}

type Row = [name: string, build: () => Ev[], steps: [who: string, text: string, mark?: string | null][]];
const rows: Row[] = [
  ["ASK_USER said: voiced and delivered, same gen", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1"), ...delivery("user", "g1")], [["Planner", "Asked you a question", "✓ Said in the chat"]]],
  ["ASK_USER voiced, never delivered", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1")], [["Planner", "Asked you a question", "Passed to the voice"]]],
  ["ASK_USER delivered under another gen", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1"), ...delivery("user", "g2")], [["Planner", "Asked you a question", "Passed to the voice"]]],
  ["voiced by a forged actor", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1", "slow"), ...delivery("user", "g1")], [["Planner", "Asked you a question", "Passed to the voice"]]],
  ["voiced by the other lane's voice", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1", "fast.cp"), ...delivery("user", "g1")], [["Planner", "Asked you a question", "Passed to the voice"]]],
  ["TELL_USER", () => [s2f("user", "TELL_USER", "m1")], [["Planner", "Updated you in the chat", "Passed to the voice"]]],
  ["GUIDE said on the call", () => [s2f("cp", "GUIDE", "m1", { guide: { move: "identify", slots: [] } }), voiced("cp", "m1", "c1"), ...delivery("cp", "c1")], [["Planner → phone voice", "Verify your identity", "✓ Said on the call"]]],
  ["GUIDE unknown move, raw", () => [s2f("cp", "GUIDE", "m1", { guide: { move: "sing_a_song", slots: [] } })], [["Planner → phone voice", "sing_a_song", "Passed to the voice"]]],
  ["s2f.msg from a forged actor", () => [s2f("user", "ASK_USER", "m1", {}, "slow")], []],
  ["APPROVAL_NOTICE and END are not steps", () => [s2f("user", "APPROVAL_NOTICE", "m1", { approval_id: "a1" }), s2f("user", "END", "m2")], []],
  ["mandate proposed, then confirmed by you", () => [mandate(), ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "mh", decision: "granted", by: "ui" })], [["Planner", "Proposed your limits"], ["You", "Confirmed your limits"]]],
  ["mandate declined by the sim approver", () => [ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "mh", decision: "denied", by: "sim_approver" })], [["Simulated approver", "Declined your limits"]]],
  ["forged mandate events", () => [ev("mandate.proposed", "slow", {}), ev("mandate.decided", "ui", { decision: "granted", by: "ui" })], []],
  ["calls: opened, ended, called back", () => [ev("chan.opened", "kernel", { lane: "cp", call: 1 }), ev("chan.closed", "kernel", { lane: "cp" }), ev("chan.opened", "kernel", { lane: "cp", call: 2 })], [["Call", "Called the company"], ["Call", "Call ended"], ["Call", "Called back"]]],
  ["the user lane's channel and a forged opener", () => [ev("chan.opened", "kernel", { lane: "user" }), ev("chan.opened", "fast.cp", { lane: "cp", call: 1 })], []],
  ["the AI disclosure, once delivered", () => verbatim("disclosure"), [["Guard", "Opened with the AI disclosure"]]],
  ["the disclosure not yet delivered", () => verbatim("disclosure").slice(0, 2), []],
  ["chan.hold by the phone voice; a resume is no step", () => [ev("chan.hold", "fast.cp", { lane: "cp", reason: "fact_request" }), ev("chan.hold", "fast.cp", { lane: "cp", reason: null })], [["Phone voice", "Asked the rep to hold"]]],
  ["chan.hold from a forged actor", () => [ev("chan.hold", "slow", { lane: "cp", reason: "fact_request" })], []],
  ["offer heard, and its revision", () => [offer(1), offer(2)], [["Offer heard", "$78.00/mo · 24 months"], ["Offer heard", "$78.00/mo · 24 months (revision 2)"]]],
  [
    "read-back updates merge into one step",
    () => [
      ev("readback.updated", "guard", { offer_ref: "o1", revision: 1, slot_statuses: { monthly_price: "confirmed", term_months: "heard" } }),
      ev("readback.updated", "guard", { offer_ref: "o1", revision: 1, slot_statuses: { monthly_price: "confirmed", term_months: "confirmed" } }),
    ],
    [["Guard", "All 2 terms read back and confirmed"]],
  ],
  ["approval asked without limits, approved by you", () => [card(), ...granted("a1")], [["Guard", "Asked for your approval"], ["You", "Approved"]]],
  [
    "approval asked outside granted limits",
    () => [ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "mh", decision: "granted", by: "ui" }), ev("authority.epoch", "kernel", { new: 1, reason: "mandate_decided" }), card("a1", 1)],
    [["You", "Confirmed your limits"], ["Guard", "Asked for your approval: outside your limits"]],
  ],
  [
    "your message pauses a pending approval, merged once read",
    () => {
      const c = card();
      const msg = ev("user.msg", "kernel", { text: "stop" });
      return [c, msg, ev("authority.fence", "kernel", { op: "raised", fence_id: "f1", utt_id: msg.event_id }, [msg]), ev("authority.fence", "kernel", { op: "cleared", fence_id: "f1", utt_id: msg.event_id })];
    },
    [["Guard", "Asked for your approval"], ["You", "Your message paused commitments; the agent read it"]],
  ],
  [
    "a fence with nothing pending, or a rep line's fence, is no step",
    () => {
      const msg = ev("user.msg", "kernel", { text: "hi" });
      return [msg, ev("authority.fence", "kernel", { op: "raised", fence_id: "f1", utt_id: msg.event_id }), card(), ev("authority.fence", "kernel", { op: "raised", fence_id: "f2", utt_id: "cp-3" })];
    },
    [["Guard", "Asked for your approval"]],
  ],
  ["epoch: your revoke; a mandate grant's own bump is no step", () => [ev("authority.epoch", "kernel", { new: 1, reason: "f2s_revoke" }), ev("authority.epoch", "kernel", { new: 2, reason: "mandate_decided" })], [["You", "Your instructions changed; earlier approvals no longer count"]]],
  ["epoch: an unknown reason, raw", () => [ev("authority.epoch", "guard", { new: 1, reason: "moon_phase" })], [["Guard", "Earlier approvals no longer count (moon_phase)"]]],
  [
    "the yes: cleared by your approval, then said",
    () => {
      const asked = [card(), ...granted("a1")]; // the grant comes before the authorization
      const [auth, said] = accept();
      const released = ev("speak.released", "kernel", { lane: "cp", cap_id: "c1" }, [said]);
      const heard = ev("utt.delivered", "kernel", { lane: "cp", utt_id: "accept-1", text_generated: "y", text_heard: "y", interrupted: false }, [released]);
      return [...asked, auth, said, released, heard];
    },
    [["Guard", "Asked for your approval"], ["You", "Approved"], ["Guard", "Cleared to say yes"], ["Phone voice", "Said yes on the call"]],
  ],
  [
    "the yes names no approver (attribution waits for grantOfAccept)",
    () => accept(),
    [["Guard", "Cleared to say yes"]],
  ],
  [
    "the yes, stopped by your message",
    () => {
      const asked = [card(), ...granted("a1", "sim_approver")];
      const [auth, said] = accept();
      return [...asked, auth, said, ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: "c1" }, [said])];
    },
    [["Guard", "Asked for your approval"], ["Simulated approver", "Approved"], ["Guard", "Cleared to say yes"], ["Guard", "Stopped the yes before it was said: you sent a message"]],
  ],
  ["a forged authorization", () => [ev("action.authorized", "slow", { intent: "accept_offer", capability: { cap_id: "c1" } })], []],
  ["private details kept", () => [ev("screen.redacted", "guard", {}), ev("declass.denied", "guard", { violations: ["$65"] }), ev("declass.denied", "slow", { violations: [] })], [["Guard", "Kept a private detail from being said"], ["Guard", "Kept a private detail from being said"]]],
  [
    "denials: authority intents only, from guard",
    () => [
      ev("action.denied", "guard", { intent: "accept_offer", reason: "not_authorized" }),
      ev("action.denied", "guard", { intent: "guide_fast", reason: "guide_slot_not_public" }),
      ev("action.denied", "kernel", { intent: "approval.post", reason: "stale" }),
    ],
    [["Guard", "Blocked: saying yes (not_authorized)"]],
  ],
  [
    "evidence and verification",
    () => [ev("evidence.recorded", "guard", { evidence_id: "ledger:C-7", kind: "ledger", confirmation_id: "C-7" }), ev("completion.decided", "guard", { verdict: "ok", reasons: [] }), ev("completion.decided", "guard", { verdict: "fail", reasons: ["x"] })],
    [["Guard", "Got confirmation C-7"], ["Guard", "Verified against the company's records"], ["Guard", "Couldn't verify: re-planning"]],
  ],
  [
    "the main view skips planner internals, model calls, relays and spend",
    () => [
      ev("slow.step.started", "slow", { basis_seq: 0, wake_reasons: [] }),
      ev("llm.call", "slow", {}),
      ev("f2s.msg", "fast.cp", { type: "HOLD", text: "t" }),
      ev("fast.turn", "fast.cp", {}),
      ev("chan.strike", "kernel", { lane: "cp" }),
      ev("spend.charged", "kernel", {}),
      ev("summary.updated", "guard", { scope: "private", text: "s" }),
      ev("status.changed", "guard", { previous: "INTAKE", status: "IN_CALL" }),
    ],
    [],
  ],
];

describe("timeline: one row per event type", () => {
  it.each(rows)("%s", (_name, build, want) => {
    const steps = timeline(build());
    expect(steps.map((s) => [s.who, s.text, ...(s.mark === null ? [] : [s.mark])])).toEqual(want);
  });

  it("groups steps by call, with session times", () => {
    const steps = timeline([mandate(), ev("chan.opened", "kernel", { lane: "cp", call: 1 }), offer(), ev("chan.closed", "kernel", { lane: "cp" }), ev("chan.opened", "kernel", { lane: "cp", call: 2 }), ev("completion.decided", "guard", { verdict: "ok" })]);
    expect(groups(steps).map((g) => [g.name, g.steps.length])).toEqual([
      ["Before the call", 1],
      ["On the call", 3],
      ["Call 2", 2],
    ]);
    const closed = timeline([ev("chan.opened", "kernel", { lane: "cp", call: 1 }), ev("chan.closed", "kernel", { lane: "cp" }), ev("evidence.recorded", "guard", { confirmation_id: "C" })]);
    expect(groups(closed).map((g) => g.name)).toEqual(["On the call", "After"]);
  });
});

describe("the status line (NowCard), one rung each", () => {
  const line = (events: Ev[]) => now(events, timeline(events), approvalCards(events, new Map()), mandateCards(events, new Map()));
  const status = (s: string) => ev("status.changed", "guard", { previous: "INTAKE", status: s });

  it.each<[string, () => Ev[], string]>([
    ["1 ended: the outcome title", () => [card(), ev("session.ended", "kernel", { reason: "abandoned" })], "Ended: the rep hung up. Not verified complete."],
    ["2 an open approval", () => [status("IN_CALL"), offer(), card()], "Waiting for you: approve or decline $78/mo for 24 months"],
    ["2 an approval already decided does not wait", () => [status("IN_CALL"), offer(), card(), ...granted("a1")], "On the call with the company"],
    ["3 limits to confirm", () => [mandate()], "Waiting for you: confirm your limits"],
    ["4 a said question with no reply", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1"), ...delivery("user", "g1")], "Waiting for your reply in the chat"],
    ["4 a question only passed to the voice does not wait", () => [s2f("user", "ASK_USER", "m1")], "Getting the details before calling"],
    ["4 a reply ends the wait", () => [s2f("user", "ASK_USER", "m1"), voiced("user", "m1", "g1"), ...delivery("user", "g1"), ev("user.msg", "kernel", { text: "x" })], "Getting the details before calling"],
    [
      "5 your message's fence",
      () => {
        const msg = ev("user.msg", "kernel", { text: "wait" });
        return [status("IN_CALL"), msg, ev("authority.fence", "kernel", { op: "raised", fence_id: "f1", utt_id: msg.event_id })];
      },
      "Reading your message before doing anything binding",
    ],
    ["5 a rep line's fence is not yours", () => [status("IN_CALL"), ev("authority.fence", "kernel", { op: "raised", fence_id: "f1", utt_id: "cp-4" })], "On the call with the company"],
    ["6 committed", () => [status("COMMITTED")], "Accepted on the call. Checking the company's records…"],
    ["7 on hold", () => [status("IN_CALL"), ev("chan.opened", "kernel", { lane: "cp", call: 1 }), ev("chan.hold", "fast.cp", { lane: "cp", reason: "fact_request" })], "Rep on hold while the agent checks something"],
    ["8 in the call", () => [status("IN_CALL")], "On the call with the company"],
    ["9 intake", () => [], "Getting the details before calling"],
    ["other statuses in words, unknown raw", () => [status("NEEDS_REPLAN")], "The last step did not go through; re-planning"],
    ["an unknown status, raw", () => [status("MOON")], "MOON"],
    ["a forged status moves nothing", () => [ev("status.changed", "slow", { status: "COMMITTED" })], "Getting the details before calling"],
  ])("%s", (_name, build, want) => {
    expect(line(build())).toBe(want);
  });
});

describe("the planner line", () => {
  const start = (roles: string[]) => ev("session.started", "kernel", { models: Object.fromEntries(roles.map((r) => [r, { ref: { kind: "test_fake" } }])) });
  it("pulses only while a step has no completion, and not without a planner or after the end", () => {
    const s = start(["slow", "fast_user"]);
    const step = ev("slow.step.started", "slow", { basis_seq: 1, wake_reasons: [] });
    expect(planner([s])).toBe("listening");
    expect(planner([s, step])).toBe("thinking");
    expect(planner([s, step, ev("slow.step.completed", "slow", { basis_seq: 1 }, [step])])).toBe("listening");
    expect(planner([s, step, ev("slow.step.completed", "kernel", { basis_seq: 1 }, [step])])).toBe("thinking");
    expect(planner([start(["fast_user"]), step])).toBeNull();
    expect(planner([s, step, ev("session.ended", "kernel", { reason: "stopped" })])).toBeNull();
  });
});

describe("the allow-list: the rail reads only PAYLOAD_KEYS", () => {
  const SENTINEL = "SENTINEL-7f3";
  /** Every event carrying the sentinel in each free-text key, in a run that touches every branch. */
  function run(): Ev[] {
    const msg = ev("user.msg", "kernel", { text: SENTINEL });
    const [auth, said] = accept();
    return [
      ev("session.started", "kernel", { models: { slow: { ref: { kind: "test_fake" } } } }),
      mandate(),
      ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "mh", decision: "granted", by: "ui" }),
      s2f("user", "ASK_USER", "m1", { text: SENTINEL }),
      voiced("user", "m1", "g1"),
      ...delivery("user", "g1").map((e) => ({ ...e, payload: { ...e.payload, text: SENTINEL, text_generated: SENTINEL, text_heard: SENTINEL } })),
      ev("summary.updated", "guard", { scope: "public", text: SENTINEL }),
      ev("f2s.msg", "fast.user", { type: "REQUEST", text: SENTINEL }),
      ev("chan.opened", "kernel", { lane: "cp", call: 1 }),
      ...verbatim("disclosure", { text: SENTINEL }),
      s2f("cp", "GUIDE", "m2", { guide: { move: "identify", slots: [] } }),
      ev("chan.hold", "fast.cp", { lane: "cp", reason: "fact_request" }),
      offer(),
      ev("readback.updated", "guard", { offer_ref: "o1", revision: 1, slot_statuses: { monthly_price: "confirmed" } }),
      card(),
      msg,
      ev("authority.fence", "kernel", { op: "raised", fence_id: "f1", utt_id: msg.event_id }),
      ...granted("a1"),
      auth,
      { ...said, payload: { ...said.payload, text: SENTINEL } },
      ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: "c1" }, [said]),
      ev("declass.denied", "guard", { violations: [SENTINEL] }),
      ev("action.denied", "guard", { intent: "share_fact", reason: "protected" }),
      ev("evidence.recorded", "guard", { confirmation_id: "C-1" }),
      ev("completion.decided", "guard", { verdict: "ok", reasons: [] }),
      ev("status.changed", "guard", { previous: "IN_CALL", status: "COMMITTED" }),
    ];
  }
  const NESTED = new Set(["guide", "capability", "slots"]);

  /** The events with every payload key read recorded (nested ones dotted, array items as []). */
  function watched(events: Ev[], read: Set<string>): Ev[] {
    const wrap = (obj: Record<string, unknown>, path: string): Record<string, unknown> =>
      new Proxy(obj, {
        get(target, key, recv) {
          const v = Reflect.get(target, key, recv) as unknown;
          if (typeof key !== "string") return v;
          const name = path ? `${path}.${key}` : key;
          read.add(name);
          if (!path && NESTED.has(key) && typeof v === "object" && v !== null) {
            return Array.isArray(v) ? v.map((x: unknown) => (typeof x === "object" && x !== null ? wrap(x as Record<string, unknown>, `${key}[]`) : x)) : wrap(v as Record<string, unknown>, key);
          }
          return v;
        },
      });
    return events.map((e) => ({ ...e, payload: wrap(e.payload, "") }));
  }

  it("names no free-text key", () => {
    for (const k of ["text", "text_generated", "text_heard", "readback_text", "violations", "facts"]) expect(PAYLOAD_KEYS).not.toContain(k);
  });

  it("reads nothing outside the list, and no sentinel reaches a step, the status line or the planner line", () => {
    const events = run();
    const read = new Set<string>();
    const w = watched(events, read);
    const cards = approvalCards(events, new Map());
    const mandates = mandateCards(events, new Map());
    const steps = timeline(w);
    const out = [steps, now(w, steps, cards, mandates), planner(w), now(w, steps, [], [])];
    expect([...read].filter((k) => !(PAYLOAD_KEYS as readonly string[]).includes(k))).toEqual([]);
    // the watch sees nested reads too, so a free-text read would show here
    for (const k of ["guide.move", "slots[].value", "capability.cap_id", "gen_id"]) expect(read.has(k)).toBe(true);
    expect(JSON.stringify(out)).not.toContain(SENTINEL);
    expect(steps.length).toBeGreaterThan(15); // the run reached the branches
  });
});
