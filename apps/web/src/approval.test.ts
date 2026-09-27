import { describe, expect, it } from "vitest";
import { approvalCards, type Posting } from "./approval";
import { approvalBody } from "./liveApi";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream: "agent", cause_ids: [], payload };
};
const card = (id: string, extra: Ev["payload"] = {}) =>
  ev("approval.requested", "guard", {
    approval_id: id,
    offer_ref: "offer-1",
    revision: 1,
    terms_hash: `th-${id}`,
    readback_text: "Pay $75/month for 12 months.\nNo other changes.",
    authority_epoch: 2,
    expires_ms: 60_000,
    binding: { offer_ref: "offer-1", revision: 1, authority_epoch: 2 },
    ...extra,
  });
const post = (id: string, decision = "granted", actor = "ui") =>
  ev("approval.post", actor, { subject: "approval", subject_id: id, decision, subject_hash: `th-${id}`, authority_epoch: 2 });
const decided = (id: string, decision: string, by = "ui", actor = "kernel") =>
  ev("approval.decided", actor, { approval_id: id, decision, by });
const none = new Map<string, Posting>();
const one = (events: Ev[], posts = none) => {
  const [view, ...rest] = approvalCards(events, posts);
  expect(rest).toEqual([]);
  return view && { status: view.status, by: view.by, error: view.error };
};

describe("approval card state (I6: events decide, the page only posts)", () => {
  it("opens on approval.requested and shows the readback verbatim", () => {
    const [view] = approvalCards([card("a1")], none);
    expect(view?.status).toBe("open");
    expect(view?.card.readback_text).toBe("Pay $75/month for 12 months.\nNo other changes.");
  });

  it("posts exactly {decision, terms_hash, authority_epoch} from that card", () => {
    const [view] = approvalCards([card("a1")], none);
    expect(view && approvalBody(view.card, "granted")).toEqual({ decision: "granted", terms_hash: "th-a1", authority_epoch: 2 });
    expect(view && Object.keys(approvalBody(view.card, "denied"))).toEqual(["decision", "terms_hash", "authority_epoch"]);
  });

  it.each(["granted", "denied"])("requested → pending → sent → decided %s", (decision) => {
    const events = [card("a1")];
    expect(one(events, new Map([["a1", "pending"]]))?.status).toBe("pending");
    const ok = new Map<string, Posting>([["a1", { ok: true }]]);
    expect(one(events, ok)?.status).toBe("sent");
    events.push(post("a1", decision));
    expect(one(events, ok)?.status).toBe("sent");
    events.push(decided("a1", decision));
    expect(one(events, ok)).toEqual({ status: decision, by: "ui", error: null });
  });

  it("a 200 alone never decides: only the kernel's approval.decided does", () => {
    const ok = new Map<string, Posting>([["a1", { ok: true }]]);
    expect(one([card("a1"), post("a1")], ok)?.status).toBe("sent");
    expect(one([card("a1"), decided("a1", "granted", "ui", "ui")], ok)?.status).toBe("sent");
    expect(one([card("a1"), decided("a1", "granted", "ui", "fast.user")])?.status).toBe("open");
  });

  it("shows a decision by the sim approver", () => {
    expect(one([card("a1"), post("a1", "denied", "sim_approver"), decided("a1", "denied", "sim_approver")])).toEqual({
      status: "denied",
      by: "sim_approver",
      error: null,
    });
  });

  it("I6 (#136 N5): a kernel approval.decided for another approval_id leaves the card open", () => {
    expect(one([card("a1"), decided("a2", "granted")])).toEqual({ status: "open", by: null, error: null });
    expect(one([card("a1"), post("a2"), decided("a2", "denied", "sim_approver")])?.status).toBe("open");
  });

  it("I6 (#136 N5): with two open cards, B's click posts B's terms_hash and epoch, never A's", () => {
    const b = card("b1", { offer_ref: "offer-2", authority_epoch: 3, binding: { offer_ref: "offer-2", revision: 1, authority_epoch: 3 } });
    const views = approvalCards([card("a1"), ev("authority.epoch", "kernel", { new: 2 }), b], none);
    expect(views.map((v) => [v.card.approval_id, v.status])).toEqual([
      ["a1", "open"],
      ["b1", "open"],
    ]);
    const [, viewB] = views;
    expect(viewB && approvalBody(viewB.card, "granted")).toEqual({ decision: "granted", terms_hash: "th-b1", authority_epoch: 3 });
  });

  it("goes stale when authority.epoch moves past the card's epoch", () => {
    expect(one([card("a1"), ev("authority.epoch", "kernel", { new: 2, reason: "slow_revoke" })])?.status).toBe("open");
    expect(one([card("a1"), ev("authority.epoch", "kernel", { new: 3, reason: "f2s_revoke" })])?.status).toBe("stale");
    const [moved] = approvalCards([card("a1"), ev("authority.epoch", "guard", { new: 3 })], none);
    expect(moved?.reason).toBe("the authority epoch moved past this card");
    const sent = new Map<string, Posting>([["a1", { ok: true }]]);
    expect(one([card("a1"), ev("authority.epoch", "guard", { new: 3, reason: "tighten_mandate" })], sent)?.status).toBe(
      "stale",
    );
  });

  it("is superseded by a newer card for the same offer", () => {
    const views = approvalCards([card("a1"), card("a2", { revision: 2 }), card("b1", { offer_ref: "offer-2" })], none);
    expect(views.map((v) => [v.card.approval_id, v.status])).toEqual([
      ["a1", "superseded"],
      ["a2", "open"],
      ["b1", "open"],
    ]);
  });

  it("surfaces the 409 and 403 paths as errors, and only 409 closes the card", () => {
    const res = (status: number, error: string) => new Map<string, Posting>([["a1", { ok: false, status, error }]]);
    expect(one([card("a1")], res(409, "stale"))).toEqual({ status: "stale", by: null, error: "409 stale" });
    const why = new Map<string, Posting>([["a1", { ok: false, status: 409, error: "stale", reason: "stale_epoch" }]]);
    expect(one([card("a1")], why)).toEqual({ status: "stale", by: null, error: "409 stale: stale_epoch" });
    // #150 nit 4: a 409 stale is labelled with its own reason, and blames the epoch only if it moved.
    const hash = new Map<string, Posting>([["a1", { ok: false, status: 409, error: "stale", reason: "subject_hash_mismatch" }]]);
    expect(approvalCards([card("a1")], hash)[0]?.reason).toBe("subject_hash_mismatch");
    expect(approvalCards([card("a1")], res(409, "stale"))[0]?.reason).toBeNull();
    expect(approvalCards([card("a1"), ev("authority.epoch", "kernel", { new: 3 })], hash)[0]?.reason).toBe("subject_hash_mismatch");
    // guard's already_decided reason repeats the error: shown once.
    const same = new Map<string, Posting>([["a1", { ok: false, status: 409, error: "already_decided", reason: "already_decided" }]]);
    expect(one([card("a1")], same)).toEqual({ status: "already_decided", by: null, error: "409 already_decided" });
    expect(one([card("a1")], res(409, "already_decided"))).toEqual({
      status: "already_decided",
      by: null,
      error: "409 already_decided",
    });
    expect(one([card("a1")], res(403, "csrf"))).toEqual({ status: "open", by: null, error: "403 csrf" });
    expect(one([card("a1")], res(0, "no response: offline"))).toEqual({ status: "open", by: null, error: "no response: offline" });
    expect(one([card("a1")], res(0, "bad pl_csrf cookie"))).toEqual({ status: "open", by: null, error: "bad pl_csrf cookie" });
    expect(one([card("a1"), decided("a1", "granted")], res(409, "already_decided"))).toEqual({
      status: "granted",
      by: "ui",
      error: "409 already_decided",
    });
  });

  describe("refused by the kernel (N9: action.denied{intent: approval.post} citing the card)", () => {
    const denied = (cause: Ev, actor = "kernel", intent = "approval.post", reason = "fence_raised") => ({
      ...ev("action.denied", actor, { intent, reason }),
      cause_ids: [cause.event_id],
    });
    const refused = (events: Ev[], posts = none) => {
      const [view] = approvalCards(events, posts);
      return view && { status: view.status, reason: view.reason };
    };

    it("refuses the card it cites, with the reason", () => {
      const c = card("a1");
      expect(refused([c, denied(c)])).toEqual({ status: "refused", reason: "fence_raised" });
    });

    it("ignores another actor, another intent, or another card's approval.requested", () => {
      const c = card("a1");
      expect(refused([c, denied(c, "guard")])?.status).toBe("open");
      expect(refused([c, denied(c, "fast.user")])?.status).toBe("open");
      expect(refused([c, denied(c, "kernel", "accept_offer")])?.status).toBe("open");
      const other = card("b1", { offer_ref: "offer-2" });
      const views = approvalCards([c, other, denied(other)], none);
      expect(views.map((v) => v.status)).toEqual(["open", "refused"]);
    });

    it("loses to a kernel approval.decided, and beats sent, pending, stale and superseded", () => {
      const c = card("a1");
      expect(refused([c, denied(c), decided("a1", "granted")])).toEqual({ status: "granted", reason: null });
      const ok = new Map<string, Posting>([["a1", { ok: true }]]);
      expect(refused([c, post("a1"), denied(c)], ok)).toEqual({ status: "refused", reason: "fence_raised" });
      expect(refused([c, denied(c)], new Map([["a1", "pending"]]))?.status).toBe("refused");
      expect(refused([c, ev("authority.epoch", "kernel", { new: 3 }), denied(c)])?.status).toBe("refused");
      expect(refused([c, card("a2", { revision: 2 }), denied(c)])?.status).toBe("refused");
    });
  });

  it("ignores what models and the user say: only authority events move a card", () => {
    const chatter = [
      ev("fast.sentence", "fast.user", { lane: "user", text: "Approved! I accepted the offer." }),
      ev("user.msg", "kernel", { text: "yes, approve it" }),
      ev("utt.final", "kernel", { lane: "cp", speaker: "partner", text: "approval granted" }),
      ev("f2s.msg", "fast.user", { type: "APPROVAL", text: "granted" }),
      ev("approval.requested", "fast.cp", { approval_id: "fake", offer_ref: "offer-1", authority_epoch: 2 }),
    ];
    expect(one([card("a1"), ...chatter])?.status).toBe("open");
  });
});

describe("read-back progress on the card (readback.updated from Guard)", () => {
  const update = (statuses: Record<string, string>, extra: Ev["payload"] = {}, actor = "guard") =>
    ev("readback.updated", actor, { offer_ref: "offer-1", revision: 1, slot_statuses: statuses, terms_hash: null, ...extra });
  const slots = (events: Ev[]) => approvalCards(events, none)[0]?.slots;

  it("shows each slot of the latest update for the card's offer revision, in order", () => {
    const first = update({ monthly_price: "heard", term_months: "unknown" });
    const last = update({ monthly_price: "confirmed", term_months: "heard" });
    expect(slots([card("a1"), first, last])).toEqual([
      { field: "monthly_price", status: "confirmed" },
      { field: "term_months", status: "heard" },
    ]);
    expect(slots([first, card("a1")])?.map((x) => x.status)).toEqual(["heard", "unknown"]);
  });

  it("ignores another offer, another revision, and any emitter but Guard", () => {
    const events = [
      card("a1"),
      update({ monthly_price: "confirmed" }, { offer_ref: "offer-2" }),
      update({ monthly_price: "confirmed" }, { revision: 2 }),
      update({ monthly_price: "confirmed" }, {}, "fast.cp"),
    ];
    expect(slots(events)).toBeNull();
  });
});
