import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { STOPPED } from "./decision";
import { parseJsonl, type Ev } from "./replay";
import { timeline, type Step } from "./timeline";
import { PAYLOAD_KEYS, todo, type RowKey, type RowState, type Todo } from "./todo";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, causes: Ev[] = []): Ev => {
  seq += 1;
  const stream = type.startsWith("session.") ? "ops" : "agent";
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq * 1000, type, actor, stream, cause_ids: causes.map((c) => c.event_id), payload };
};

const mandate = () => ev("mandate.proposed", "guard", { mandate_id: "m1", mandate_hash: "mh", status: "proposed", epoch: 0, max_monthly_price_minor: 6500 });
const limits = (decision: string, by = "ui") => ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "mh", decision, by });
const call = () => ev("chan.opened", "kernel", { lane: "cp", call: 1 });
const offer = (ref = "o1", revision = 1, hash = "h1") =>
  ev("offer.recorded", "guard", {
    offer_ref: ref,
    revision,
    terms_hash: hash,
    slots: [
      { field: "monthly_price", value: "7800", unit: "usd_minor" },
      { field: "term_months", value: "24", unit: "months" },
    ],
  });
const readback = (price: string, term: string, ref = "o1", revision = 1) =>
  ev("readback.updated", "guard", { offer_ref: ref, revision, slot_statuses: { monthly_price: price, term_months: term } });
const ALL = () => readback("confirmed", "confirmed");
const card = (epoch = 0) =>
  ev("approval.requested", "guard", { approval_id: "a1", offer_ref: "o1", revision: 1, terms_hash: "h1", readback_text: "rb", authority_epoch: epoch, expires_ms: 9e6, binding: {} });
const post = (by = "ui") => ev("approval.post", by, { subject: "approval", subject_id: "a1", decision: "granted", subject_hash: "h1", authority_epoch: 0 });
const decided = (decision: string, by = "ui") => ev("approval.decided", "kernel", { approval_id: "a1", decision, by });
const bump = (n = 1) => ev("authority.epoch", "kernel", { new: n, reason: "slow_revoke" });
/** Guard's authorization citing `grant` (slow/authority.py), and its accept line. */
const authorized = (grant?: Ev) => ev("action.authorized", "guard", { intent: "accept_offer", capability: { cap_id: "c1", terms_hash: "h1", epoch: 0 } }, grant ? [grant] : []);
const said = () => ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: "c1" });
const released = (line: Ev) => ev("speak.released", "kernel", { lane: "cp", cap_id: "c1" }, [line]);
const revoked = (line: Ev) => ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: "c1" }, [line]);
const heard = (release: Ev, interrupted = false, text = "Yes, we accept.") =>
  ev("utt.delivered", "kernel", { lane: "cp", utt_id: "accept-1", text_generated: "Yes, we accept.", text_heard: text, interrupted }, [release]);
const status = (s: string) => ev("status.changed", "guard", { previous: "IN_CALL", status: s });
const evidence = () => ev("evidence.recorded", "guard", { confirmation_id: "C-1" });
const verdict = (v: string) => ev("completion.decided", "guard", { verdict: v, reasons: v === "ok" ? [] : ["no_record"] });
const ended = (reason = "completed") => ev("session.ended", "kernel", { reason, counts: {} });

/** An accept cleared by `grant`, said, released and heard whole. */
function accepted(grant?: Ev): Ev[] {
  const line = said();
  const release = released(line);
  return [authorized(grant), line, release, heard(release)];
}
/** A granted approval run up to the heard yes. */
function approvedRun(by = "ui"): Ev[] {
  const m = mandate();
  const g = limits("granted");
  const d = decided("granted", by);
  return [m, g, call(), offer(), ALL(), card(), post(by), d, ...accepted(d)];
}

const run = (events: Ev[]): Todo => todo(events, timeline(events));
const row = (t: Todo, key: RowKey) => t.rows.find((r) => r.key === key);

type Expect = { state: RowState; note?: string | null } | "absent";
type Case = [name: string, key: RowKey, build: () => Ev[], want: Expect];

// Rows × states (S1-SYS-79 table): pending, current, needs you, done, done with a note, not reached, absent.
const CASES: Case[] = [
  // 1. Set your limits (approval kind only)
  ["limits: absent before any kind", "limits", () => [], "absent"],
  ["limits: absent in an info case", "limits", () => [call(), offer()], "absent"],
  ["limits: pending in an approval case without limits", "limits", () => [call(), offer(), ALL(), card()], { state: "pending" }],
  ["limits: needs you while proposed", "limits", () => [mandate()], { state: "needs_you", note: "Waiting for your confirmation" }],
  ["limits: needs you after the click, until the kernel decides", "limits", () => [mandate(), ev("approval.post", "ui", { subject: "mandate", subject_id: "m1", decision: "granted" })], { state: "needs_you", note: "Sent. Waiting for Guard to record it" }],
  ["limits: current (not you) once the proposal went stale", "limits", () => [mandate(), bump()], { state: "current", note: "No longer valid: your instructions changed" }],
  ["limits: done, confirmed by you", "limits", () => [mandate(), limits("granted", "ui")], { state: "done", note: "Confirmed by you" }],
  ["limits: done, confirmed by the sim approver", "limits", () => [mandate(), limits("granted", "sim_approver")], { state: "done", note: "Confirmed by the simulated approver (not you)" }],
  ["limits: declined is done with a note", "limits", () => [mandate(), limits("denied")], { state: "noted", note: "Declined your limits" }],
  ["limits: not reached after the end", "limits", () => [call(), offer(), card(), ended("timeout")], { state: "not_reached", note: "Not reached" }],
  // 2. Call the company
  ["call: current at the start", "call", () => [], { state: "current" }],
  ["call: pending while the limits wait for you", "call", () => [mandate()], { state: "pending" }],
  ["call: done on the kernel's cp chan.opened", "call", () => [call()], { state: "done" }],
  ["call: the user lane's channel is not the call", "call", () => [ev("chan.opened", "kernel", { lane: "user" })], { state: "current" }],
  ["call: not reached after the end", "call", () => [ended("error")], { state: "not_reached", note: "Not reached" }],
  // 3. Hear an offer
  ["offer: pending before the call", "offer", () => [], { state: "pending" }],
  ["offer: current on the call", "offer", () => [call()], { state: "current" }],
  ["offer: done, one offer", "offer", () => [call(), offer()], { state: "done", note: "1 offer heard · latest $78/mo for 24 months" }],
  ["offer: done, two offers", "offer", () => [call(), offer(), offer("o2", 1, "h2")], { state: "done", note: "2 offers heard · latest $78/mo for 24 months" }],
  ["offer: not reached after the end", "offer", () => [call(), ended("abandoned")], { state: "not_reached", note: "Not reached" }],
  // 4. Have every term read back
  ["readback: pending on the call", "readback", () => [call()], { state: "pending" }],
  ["readback: current, partly read back", "readback", () => [call(), offer(), readback("confirmed", "heard")], { state: "current", note: "Read back · 1 of 2" }],
  ["readback: done, every term read back", "readback", () => [call(), offer(), ALL()], { state: "done", note: "Read back · 2 of 2" }],
  ["readback: a newer offer reopens it", "readback", () => [call(), offer(), ALL(), offer("o1", 2, "h2")], { state: "current", note: "Read back · 0 of 2" }],
  ["readback: not reached after the end", "readback", () => [call(), offer(), readback("confirmed", "heard"), ended("abandoned")], { state: "not_reached", note: "Not reached" }],
  // 5. Get your decision (only once Guard asks)
  ["decision: absent without approval.requested", "decision", () => [mandate(), limits("granted"), call(), offer(), ALL()], "absent"],
  ["decision: needs you while the card is open", "decision", () => [call(), offer(), ALL(), card()], { state: "needs_you", note: "Waiting for your decision" }],
  ["decision: still needs you after the click, until approval.decided", "decision", () => [call(), offer(), ALL(), card(), post()], { state: "needs_you", note: "Sent. Waiting for Guard to record it" }],
  ["decision: pending while the limits are the current need", "decision", () => [mandate(), call(), offer(), card()], { state: "pending", note: "Waiting for your decision" }],
  ["decision: current (not you) once the card went stale", "decision", () => [call(), offer(), card(), bump()], { state: "current", note: "No longer valid: your instructions changed" }],
  ["decision: done, approved by your click", "decision", () => [call(), offer(), ALL(), card(), post(), decided("granted", "ui")], { state: "done", note: "Approved by your click" }],
  ["decision: done, approved by the sim approver", "decision", () => [call(), offer(), ALL(), card(), decided("granted", "sim_approver")], { state: "done", note: "Approved by the simulated approver (not you)" }],
  ["decision: declined is done with a note", "decision", () => [call(), offer(), ALL(), card(), decided("denied")], { state: "noted", note: "Declined" }],
  ["decision: an undecided card at the end is not reached", "decision", () => [call(), offer(), ALL(), card(), ended("timeout")], { state: "not_reached", note: "Not reached" }],
  // 6. Accept on the call
  ["accept: absent in an info case", "accept", () => [call(), offer(), ALL()], "absent"],
  ["accept: pending in an approval case", "accept", () => [mandate(), limits("granted"), call()], { state: "pending" }],
  ["accept: current on action.authorized", "accept", () => [mandate(), limits("granted"), call(), offer(), ALL(), authorized()], { state: "current" }],
  ["accept: current while the line is held", "accept", () => [mandate(), limits("granted"), call(), offer(), ALL(), authorized(), said()], { state: "current" }],
  ["accept: shown for an info case once authorized", "accept", () => [call(), offer(), ALL(), authorized()], { state: "current" }],
  ["accept: done on the kernel's release, heard whole", "accept", () => [mandate(), limits("granted"), call(), offer(), ALL(), ...accepted()], { state: "done", note: "Said yes on the call" }],
  [
    "accept: released but cut off before any word is done with a note",
    "accept",
    () => {
      const line = said();
      const release = released(line);
      return [mandate(), limits("granted"), call(), offer(), ALL(), authorized(), line, release, heard(release, true, "")];
    },
    { state: "noted", note: "Started to say yes; the rep cut in" },
  ],
  [
    "accept: revoked is done with a note",
    "accept",
    () => {
      const line = said();
      return [mandate(), limits("granted"), call(), offer(), ALL(), authorized(), line, revoked(line)];
    },
    { state: "noted", note: STOPPED },
  ],
  ["accept: not reached after the end", "accept", () => [mandate(), limits("granted"), call(), ended("abandoned")], { state: "not_reached", note: "Not reached" }],
  // 7. Check the company's records (only when its events appear)
  ["records: absent without its events", "records", () => [...approvedRun()], "absent"],
  ["records: current on EVIDENCE_PENDING", "records", () => [...approvedRun(), status("EVIDENCE_PENDING")], { state: "current" }],
  ["records: current on evidence.recorded", "records", () => [...approvedRun(), evidence()], { state: "current" }],
  ["records: done, matched", "records", () => [...approvedRun(), evidence(), verdict("ok")], { state: "done", note: "Matched the company's records" }],
  ["records: a failed check is done with a note", "records", () => [...approvedRun(), evidence(), verdict("fail")], { state: "noted", note: "Didn't match the company's records" }],
  ["records: new evidence after a failed check reopens it", "records", () => [...approvedRun(), evidence(), verdict("fail"), evidence()], { state: "current" }],
  ["records: an unfinished check at the end is not reached", "records", () => [...approvedRun(), evidence(), ended("timeout")], { state: "not_reached", note: "Not reached" }],
  // 8. Result (always)
  ["result: pending at the start", "result", () => [], { state: "pending" }],
  ["result: current once every row before it is done", "result", () => [call(), offer(), ALL()], { state: "current" }],
  ["result: done, verified", "result", () => [...approvedRun(), evidence(), verdict("ok"), status("VERIFIED_COMPLETE"), ended("completed")], { state: "done", note: "Done. Verified." }],
  ["result: done, information only", "result", () => [call(), status("CLOSED_NO_ACTION"), ended("info_only")], { state: "done", note: "Here's what they offered · nothing accepted (information only)" }],
  ["result: an error is done with a note", "result", () => [call(), ended("error")], { state: "noted", note: "An error stopped the case. Not completed." }],
];

describe("todo rows × states", () => {
  it.each(CASES)("%s", (_name, key, build, want) => {
    const r = row(run(build()), key);
    if (want === "absent") {
      expect(r).toBeUndefined();
      return;
    }
    expect(r?.state).toBe(want.state);
    if (want.note !== undefined) expect(r?.note ?? null).toBe(want.note);
  });

  it.each(CASES)("%s: one row is current (or needs you) before the end, none after", (_name, _key, build) => {
    const events = build();
    const t = run(events);
    const live = t.rows.filter((r) => r.state === "current" || r.state === "needs_you");
    const over = events.some((e) => e.type === "session.ended" && e.actor === "kernel");
    expect(live).toHaveLength(over ? 0 : 1);
    if (over) expect(t.rows.filter((r) => r.state === "pending")).toEqual([]);
  });
});

describe("kind", () => {
  it.each([
    ["unknown before anything", () => [], "unknown", ["call", "offer", "readback", "result"]],
    ["approval on mandate.proposed", () => [mandate()], "approval", ["limits", "call", "offer", "readback", "accept", "result"]],
    ["approval on approval.requested", () => [call(), offer(), card()], "approval", ["limits", "call", "offer", "readback", "decision", "accept", "result"]],
    ["info on the cp call with no limits before it", () => [call()], "info", ["call", "offer", "readback", "result"]],
    ["approval when the limits came before the call", () => [mandate(), limits("granted"), call()], "approval", ["limits", "call", "offer", "readback", "accept", "result"]],
  ] as const)("%s", (_n, build, kind, keys) => {
    const t = run(build());
    expect(t.kind).toBe(kind);
    expect(t.rows.map((r) => r.key)).toEqual(keys);
  });
});

describe("summary tag", () => {
  it.each([
    ["needs you while the limits wait", () => [mandate()], "you", "Needs you · 0 of 6 done"],
    ["needs you while the card is open", () => [call(), offer(), ALL(), card()], "you", "Needs you · 3 of 7 done"],
    ["plain while the agent works", () => [call()], "plain", "1 of 4 done"],
    ["plain after the kernel decides the card", () => [call(), offer(), ALL(), card(), post(), decided("granted")], "plain", "4 of 7 done"],
    ["all done on VERIFIED_COMPLETE", () => [...approvedRun(), evidence(), verdict("ok"), status("VERIFIED_COMPLETE"), ended()], "ok", "All done · 8 of 8"],
    ["an info-only end is not 'all done'", () => [call(), offer(), ALL(), status("CLOSED_NO_ACTION"), ended("info_only")], "plain", "4 of 4 done"],
    // VERIFIED_COMPLETE with a row not reached (no limits were set): never "n of n" when a row was not done.
    [
      "verified with a row not reached says the true count",
      () => {
        const d = decided("granted");
        return [call(), offer(), ALL(), card(), d, ...accepted(d), evidence(), verdict("ok"), status("VERIFIED_COMPLETE"), ended()];
      },
      "plain",
      "7 of 8 done",
    ],
  ] as const)("%s", (_n, build, tone, text) => {
    expect(run(build()).tag).toEqual({ tone, text });
  });
});

describe("the root's required runs", () => {
  it("a within-mandate accept (no approval.requested): no decision row, the accept done, nothing 'not reached'", () => {
    const m = mandate();
    const g = limits("granted");
    const events = [m, g, call(), offer(), ALL(), ...accepted(g), status("COMMITTED"), ended("completed")];
    const t = run(events);
    expect(row(t, "decision")).toBeUndefined();
    expect(row(t, "accept")?.state).toBe("done");
    expect(t.rows.filter((r) => r.state === "not_reached")).toEqual([]);
    expect(t.rows.map((r) => [r.key, r.state])).toEqual([
      ["limits", "done"],
      ["call", "done"],
      ["offer", "done"],
      ["readback", "done"],
      ["accept", "done"],
      ["result", "noted"], // "Accepted on the call. Not verified yet."
    ]);
  });

  it.each([
    ["CLOSED_NO_ACTION", "info_only"],
    ["VERIFIED_NO_DEAL", "no_deal"],
  ])("an info run ending %s: no limits, decision or accept row; no records row without its events", (end, reason) => {
    const events = [call(), offer(), ALL(), status(end), ended(reason)];
    const t = run(events);
    expect(t.kind).toBe("info");
    expect(t.rows.map((r) => [r.key, r.state])).toEqual([
      ["call", "done"],
      ["offer", "done"],
      ["readback", "done"],
      ["result", "done"],
    ]);
    // Its records row appears only with its events.
    expect(row(run([call(), offer(), ALL(), evidence(), status(end), ended(reason)]), "records")?.state).toBe("not_reached");
  });
});

/** Each trigger: a run it would move, the event (re-emitted by the right and a wrong actor), and what follows it. */
type Setup = { base: Ev[]; event: Ev; after?: Ev[] };
type Trigger = [name: string, setup: () => Setup, right: string, wrong: string];
const granted = () => [mandate(), limits("granted"), call(), offer(), ALL()];
const TRIGGERS: Trigger[] = [
  ["mandate.proposed", () => ({ base: [], event: mandate() }), "guard", "slow"],
  ["mandate.decided", () => ({ base: [mandate()], event: limits("granted") }), "kernel", "ui"],
  ["chan.opened", () => ({ base: [], event: call() }), "kernel", "fast.cp"],
  ["offer.recorded", () => ({ base: [call()], event: offer() }), "guard", "slow"],
  ["readback.updated", () => ({ base: [call(), offer()], event: ALL() }), "guard", "slow"],
  ["approval.requested", () => ({ base: [call(), offer(), ALL()], event: card() }), "guard", "slow"],
  ["approval.decided", () => ({ base: [call(), offer(), ALL(), card()], event: decided("granted") }), "kernel", "ui"],
  ["action.authorized", () => ({ base: [call(), offer(), ALL()], event: authorized() }), "guard", "slow"],
  [
    "speak.verbatim accept",
    () => {
      const base = [...granted(), authorized()];
      const line = said();
      return { base, event: line, after: [released(line)] };
    },
    "guard",
    "slow",
  ],
  [
    "speak.released",
    () => {
      const line = said();
      return { base: [...granted(), authorized(), line], event: released(line) };
    },
    "kernel",
    "guard",
  ],
  [
    "speak.revoked",
    () => {
      const line = said();
      return { base: [...granted(), authorized(), line], event: revoked(line) };
    },
    "kernel",
    "slow",
  ],
  ["status.changed EVIDENCE_PENDING", () => ({ base: approvedRun(), event: status("EVIDENCE_PENDING") }), "guard", "kernel"],
  ["evidence.recorded", () => ({ base: approvedRun(), event: evidence() }), "guard", "slow"],
  ["completion.decided", () => ({ base: [...approvedRun(), evidence()], event: verdict("ok") }), "guard", "slow"],
  [
    "status.changed VERIFIED_COMPLETE",
    () => ({ base: [...approvedRun(), evidence(), verdict("ok")], event: status("VERIFIED_COMPLETE"), after: [ended()] }),
    "guard",
    "slow",
  ],
  ["session.ended", () => ({ base: [call()], event: ended() }), "kernel", "guard"],
];

describe("a wrong actor moves nothing", () => {
  it.each(TRIGGERS)("%s", (_name, setup, right, wrong) => {
    const { base, event, after = [] } = setup();
    const at = (actor: string | null) => todo([...base, ...(actor ? [{ ...event, actor }] : []), ...after], []);
    expect(at(right)).not.toEqual(at(null)); // the right actor moves it (the test is not vacuous) …
    expect(at(wrong)).toEqual(at(null)); // … and a wrong one moves nothing
  });
});

describe("steps: every Step lands under exactly one row, or under Other steps", () => {
  const step = (s: number): Step => ({ key: String(s), seq: s, t_ms: s, group: "g", kind: "k", who: "w", text: "t", icon: "guard", mark: null });

  it("a step before the first row starts goes to Other steps; each later one to the row that started last before it", () => {
    seq = 100;
    const early = step(101);
    seq = 101;
    const c = call(); // 102
    const mid = step(103);
    seq = 103;
    const o = offer(); // 104
    const late = step(105);
    const t = todo([c, o], [early, mid, late]);
    expect(t.other).toEqual([early]);
    expect(row(t, "call")?.steps).toEqual([mid]);
    expect(row(t, "offer")?.steps).toEqual([late]);
    expect(row(t, "result")?.steps).toEqual([]);
  });

  it("the full approval run: nothing lost, nothing duplicated, and the rows' steps in order", () => {
    const events = [...approvedRun(), evidence(), verdict("ok"), status("VERIFIED_COMPLETE"), ended()];
    const steps = timeline(events);
    const t = todo(events, steps);
    const placed = [...t.rows.flatMap((r) => r.steps), ...t.other];
    expect(placed.map((s) => s.key).sort()).toEqual(steps.map((s) => s.key).sort());
    expect(new Set(placed.map((s) => s.key)).size).toBe(placed.length);
    expect(row(t, "decision")?.steps.map((s) => s.text)).toEqual(["Asked for your approval", "Approved"]);
    expect(row(t, "accept")?.steps.map((s) => s.text)).toEqual(["Cleared to say yes (your approval)", "Said yes on the call"]);
  });
});

describe("the allow-list: todo reads only PAYLOAD_KEYS", () => {
  const SENTINEL = "SENTINEL-9c1";
  const NESTED = new Set(["capability", "slots"]);
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
  /** Every row's events, each free-text key carrying the sentinel. */
  function sentinelRun(): Ev[] {
    const text = { text: SENTINEL, summary: SENTINEL };
    const m = { ...mandate(), payload: { ...mandate().payload, ...text } };
    const g = limits("granted");
    const d = decided("granted");
    const line = said();
    const release = released(line);
    return [
      ev("user.msg", "kernel", text),
      m,
      g,
      ev("summary.updated", "guard", { scope: "public", text: SENTINEL }),
      call(),
      ev("s2f.msg", "guard", { msg_id: "x", lane: "user", type: "ASK_USER", ...text }),
      offer(),
      ALL(),
      { ...card(), payload: { ...card().payload, readback_text: SENTINEL } },
      post(),
      d,
      authorized(d),
      { ...line, payload: { ...line.payload, text: SENTINEL } },
      release,
      heard(release, false, SENTINEL),
      evidence(),
      verdict("ok"),
      status("VERIFIED_COMPLETE"),
      ev("session.ended", "kernel", { reason: "completed", counts: {}, note: SENTINEL }),
    ];
  }

  it("names no free-text key", () => {
    for (const k of ["text", "text_generated", "text_heard", "readback_text", "summary", "note", "result_text"]) expect(PAYLOAD_KEYS).not.toContain(k);
  });

  it.each([
    ["the whole run", () => sentinelRun(), true],
    ["mid-run, a card open", () => sentinelRun().slice(0, 10), false],
  ])("%s: reads nothing outside the list, and no sentinel reaches the to-do", (_n, build, nested) => {
    const events = build();
    const read = new Set<string>();
    const t = todo(watched(events, read), timeline(events));
    expect([...read].filter((k) => !(PAYLOAD_KEYS as readonly string[]).includes(k))).toEqual([]);
    expect(JSON.stringify({ ...t, rows: t.rows.map((r) => ({ ...r, steps: [] })) })).not.toContain(SENTINEL);
    if (nested) expect(read.has("capability.cap_id")).toBe(true); // the watch sees nested reads
  });
});

describe("committed bundles (web fixtures, the superseded golden, evidence/s0 the wiring e2e serves)", () => {
  const root = fileURLToPath(new URL("../../../", import.meta.url));
  const dirs = (d: string) => readdirSync(join(root, d)).map((n) => join(root, d, n, "events.jsonl"));
  const bundles = [...dirs("tests/web/fixtures"), join(root, "tests/web/superseded/events.jsonl"), ...dirs("evidence/s0")];

  it("finds the bundles", () => expect(bundles.length).toBeGreaterThanOrEqual(6));

  it.each(bundles)("%s: at every prefix, one current row (none after the end), and every Step under exactly one row", (path) => {
    const all = parseJsonl<Ev>(readFileSync(path, "utf-8"));
    for (let n = 0; n <= all.length; n += 1) {
      const events = all.slice(0, n);
      const steps = timeline(events);
      const t = todo(events, steps);
      const over = events.some((e) => e.type === "session.ended" && e.actor === "kernel");
      expect(t.rows.filter((r) => r.state === "current" || r.state === "needs_you")).toHaveLength(over ? 0 : 1);
      const placed = [...t.rows.flatMap((r) => r.steps), ...t.other].map((s) => s.key);
      expect(placed.slice().sort()).toEqual(steps.map((s) => s.key).sort());
    }
  });
});
