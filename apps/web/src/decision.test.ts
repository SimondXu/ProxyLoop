import { describe, expect, it } from "vitest";
import { approvalCards, type CardStatus, type CardView, type Posting } from "./approval";
import { acceptOf, approvalStatusText, approvedBy, headline, priceLimit, why } from "./decision";
import { mandateCards } from "./mandate";
import type { Ev } from "./replay";
import { aboutClock, termRow, termRows, usd } from "./terms";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, cause_ids: string[] = [], wall?: string): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream: "agent", cause_ids, payload, wall };
};
const CARD = {
  approval_id: "a1",
  offer_ref: "offer-1",
  revision: 1,
  terms_hash: "th",
  readback_text: "monthly price $78.00; term months 24 months",
  authority_epoch: 2,
  expires_ms: 540_000,
  binding: {},
};
const slot = (field: string, value: string, unit: string, status = "confirmed") => ({ field, value, unit, role: "recurring", status });
const offer = (extra: Ev["payload"] = {}) =>
  ev("offer.recorded", "guard", {
    offer_ref: "offer-1",
    revision: 1,
    terms_hash: "th",
    slots: [slot("monthly_price", "7800", "usd_minor"), slot("term_months", "24", "months"), slot("fees_none", "true", "bool")],
    ...extra,
  });
const none = new Map<string, Posting>();
const authorized = (cap_id: string, terms_hash: string, epoch: number) =>
  ev("action.authorized", "guard", { intent: {}, capability: { cap_id, terms_hash, epoch } });
const view = (status: CardStatus, extra: Partial<CardView> = {}): CardView =>
  ({ seq: 1, card: CARD, status, by: null, error: null, reason: null, slots: null, ...extra }) as CardView;

describe("terms (display only, rule 13)", () => {
  it("maps each slot kind to a plain row; money is minor units", () => {
    expect(termRow("monthly_price", "7800")).toEqual(["Monthly price", "$78.00"]);
    expect(termRow("term_months", "24")).toEqual(["Contract length", "24 months"]);
    expect(termRow("fees_none", "true")).toEqual(["One-time fees", "None"]);
    expect(termRow("changes_none", "true")).toEqual(["Changes to your plan", "None"]);
    expect(termRow("fee:activation", "3500")).toEqual(["Fee: activation", "$35.00"]);
    expect(termRow("credit:loyalty", "1000")).toEqual(["Credit: loyalty", "$10.00"]);
    expect(termRow("applied_change:plan_x", "true")).toEqual(["Plan change", "plan_x"]);
    expect(termRow("applied_change:plan_x", "false")).toEqual(["No plan change", "plan_x"]);
    expect(termRow("feature:hotspot", "true")).toEqual(["Includes", "hotspot"]);
    expect(termRow("feature:hotspot", "false")).toEqual(["Not included", "hotspot"]);
    // Only "true" is included: an empty or malformed boolean is shown as sent.
    expect(termRow("feature:hotspot", "")).toEqual(["feature:hotspot", ""]);
    expect(termRow("feature:hotspot", "yes")).toEqual(["feature:hotspot", "yes"]);
    expect(termRow("applied_change:plan_x", "")).toEqual(["applied_change:plan_x", ""]);
    expect(termRow("fees_none", "false")).toEqual(["One-time fees apply", ""]);
    expect(termRow("fees_none", "maybe")).toEqual(["One-time fees", "maybe"]);
    expect(termRow("expires", "none")).toEqual(["No expiry date", ""]);
    expect(termRow("expires", "2026-10-01T00:00:00Z")[1]).toMatch(/^[A-Z][a-z]{2} \d{1,2}, \d{1,2}:\d{2}\s?[AP]M$/);
    expect(termRow("monthly_price", "78.5")).toEqual(["Monthly price", "78.5"]); // not whole cents: as sent
    expect(usd(6500)).toBe("$65.00");
  });

  it("rows follow Guard's read-back, valued from the card's own offer revision", () => {
    const rb = ev("readback.updated", "guard", { offer_ref: "offer-1", revision: 1, slot_statuses: { monthly_price: "confirmed", term_months: "heard" } });
    const rows = termRows([offer(), rb], CARD);
    expect(rows.map((r) => [r.label, r.value, r.status])).toEqual([
      ["Monthly price", "$78.00", "confirmed"],
      ["Contract length", "24 months", "heard"],
    ]);
    // Another revision or a mismatching terms hash is not this card's offer.
    expect(termRows([offer({ revision: 2 }), rb], CARD).map((r) => r.value)).toEqual(["", ""]);
    expect(termRows([offer({ terms_hash: "other" }), rb], CARD).map((r) => r.value)).toEqual(["", ""]);
    // No read-back yet: the offer's own slots and statuses.
    expect(termRows([offer()], CARD).map((r) => r.field)).toEqual(["monthly_price", "term_months", "fees_none"]);
  });

  it("the expiry hint is session.started's wall plus expires_ms, as a time of day", () => {
    const start = ev("session.started", "kernel", {}, [], "2026-09-27T14:30:00Z");
    expect(aboutClock([start], 540_000)).toBe(`about ${new Date("2026-09-27T14:39:00Z").toLocaleString("en-US", { hour: "numeric", minute: "2-digit" })}`);
    expect(aboutClock([], 540_000)).toBeNull();
  });
});

describe("approval card words", () => {
  it("never says approved before the kernel decides (redesign §7 risk 3)", () => {
    for (const s of ["open", "pending", "sent", "stale", "superseded", "already_decided", "refused"] as const) {
      for (const reason of [null, "stale_epoch", "fence_raised", "card_expired", "no_pending_card"]) {
        expect(approvalStatusText(view(s, { reason, by: "ui" }), [])).not.toMatch(/approv/i);
      }
    }
    expect(approvalStatusText(view("open"), [])).toBe("Waiting for your decision");
    expect(approvalStatusText(view("sent"), [])).toBe("Sent. Waiting for Guard to record it");
  });

  it("names who decided, and why a card closed, in plain words", () => {
    const decided = ev("approval.decided", "kernel", { approval_id: "a1", decision: "granted", by: "ui" }, [], "2026-09-27T14:30:00Z");
    expect(approvalStatusText(view("granted", { by: "ui" }), [decided])).toMatch(/^You approved · \d{1,2}:\d{2}\s?[AP]M$/);
    expect(approvalStatusText(view("granted", { by: "sim_approver" }), [])).toBe("Approved by the simulated approver (not you)");
    expect(approvalStatusText(view("denied", { by: "ui" }), [])).toBe("You declined");
    expect(approvalStatusText(view("stale", { reason: "the authority epoch moved past this card" }), [])).toBe(
      "No longer valid: your instructions changed",
    );
    expect(approvalStatusText(view("stale", { reason: "card_expired" }), [])).toBe("No longer valid: the offer expired");
    expect(approvalStatusText(view("stale", { reason: "brand_new" }), [])).toBe("No longer valid: brand_new");
    expect(approvalStatusText(view("refused", { reason: "fence_raised" }), [])).toBe("Not accepted by the system: your new message came first");
    // Unknown reasons are shown raw, never dropped or reworded.
    expect(approvalStatusText(view("refused", { reason: "kernel_new_reason" }), [])).toBe("Not accepted by the system: kernel_new_reason");
    expect(approvalStatusText(view("stale", { reason: "guard_new_reason" }), [])).toBe("No longer valid: guard_new_reason");
  });

  it("headline and limit label come from the rows and the granted mandate, with no arithmetic", () => {
    const rows = termRows([offer()], CARD);
    expect(headline(rows)).toBe("Accept $78 a month for 24 months?");
    expect(headline([])).toBe("Accept this offer?");
    const m = ev("mandate.proposed", "guard", { mandate_id: "m1", mandate_hash: "h", epoch: 1, max_monthly_price_minor: 6500 });
    const granted = [m, ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "h", decision: "granted", by: "ui" })];
    expect(priceLimit(mandateCards(granted, none))).toBe("your limit $65.00");
    expect(priceLimit(mandateCards([m], none))).toBeNull();
    expect(why(mandateCards(granted, none))).toMatch(/^It's outside the limits you confirmed/);
    expect(why([])).toMatch(/^You haven't set limits/);
    const bySim = [m, ev("mandate.decided", "kernel", { mandate_id: "m1", mandate_hash: "h", decision: "granted", by: "sim_approver" })];
    expect(why(mandateCards(bySim, none))).toMatch(/^It's outside the limits the simulated approver confirmed/);
    // A newer proposal replaces the granted one without an epoch bump: no limit from the old one.
    const replaced = mandateCards([...granted, ev("mandate.proposed", "guard", { mandate_id: "m2", mandate_hash: "h2", epoch: 1, max_monthly_price_minor: 5000 })], none);
    expect(replaced.map((v) => v.status)).toEqual(["superseded", "open"]);
    expect([priceLimit(replaced), why(replaced)]).toEqual([null, "You haven't set limits, so the agent needs your OK."]);
  });

  it("follows the accept Guard minted after this card's grant: held, released or revoked", () => {
    const card = ev("approval.requested", "guard", CARD);
    const decided = ev("approval.decided", "kernel", { approval_id: "a1", decision: "granted", by: "ui" });
    const auth = authorized("c1", "th", 2);
    const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "yes", cap_id: "c1" });
    const [v] = approvalCards([card, decided], none);
    expect(v && acceptOf([card, decided], v).state).toBe("none");
    expect(v && acceptOf([card, decided, auth, said], v).state).toBe("held");
    const revoked = ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: "c1" }, [said.event_id]);
    expect(v && acceptOf([card, decided, auth, said, revoked], v)).toEqual({ state: "revoked", reason: "fence" });
    const released = ev("speak.released", "kernel", { lane: "cp", cap_id: "c1" }, [said.event_id]);
    expect(v && acceptOf([card, decided, auth, said, released], v).state).toBe("released");
    const fake = ev("speak.released", "fast.cp", { lane: "cp" }, [said.event_id]);
    expect(v && acceptOf([card, decided, auth, said, fake], v).state).toBe("held");
    // No capability of this card's terms and epoch behind the accept: not this card's.
    expect(v && acceptOf([card, decided, said, released], v).state).toBe("none");
  });

  it("binds the accept to its own card: with two granted cards, progress never attaches to the other one", () => {
    const CARD2 = { ...CARD, approval_id: "a2", offer_ref: "offer-2", terms_hash: "th2" };
    const c1 = ev("approval.requested", "guard", CARD);
    const g1 = ev("approval.decided", "kernel", { approval_id: "a1", decision: "granted", by: "ui" });
    const c2 = ev("approval.requested", "guard", CARD2);
    const g2 = ev("approval.decided", "kernel", { approval_id: "a2", decision: "granted", by: "sim_approver" });
    const auth = authorized("c2", "th2", 2);
    const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "yes", cap_id: "c2" });
    const released = ev("speak.released", "kernel", { lane: "cp", cap_id: "c2" }, [said.event_id]);
    const events = [c1, g1, c2, g2, auth, said, released];
    const [v1, v2] = approvalCards(events, none);
    expect(v1 && acceptOf(events, v1).state).toBe("none");
    expect(v2 && acceptOf(events, v2).state).toBe("released");
    expect(v2 && approvedBy(events, v2)).toBe("Approved by the simulated approver (not you)");
    // A capability minted before the grant does not carry it.
    const minted = authorized("c3", "th2", 2);
    const grant = ev("approval.decided", "kernel", { approval_id: "a2", decision: "granted", by: "ui" });
    const early = [c2, minted, grant, ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "yes", cap_id: "c3" })];
    const [e2] = approvalCards(early, none);
    expect(e2 && acceptOf(early, e2).state).toBe("none");
  });

  it("names you as the approver only on the kernel's grant by the UI, with its time", () => {
    const c = ev("approval.requested", "guard", CARD);
    const g = ev("approval.decided", "kernel", { approval_id: "a1", decision: "granted", by: "ui" }, [], "2026-09-27T14:30:00Z");
    const [v] = approvalCards([c, g], none);
    expect(v && approvedBy([c, g], v)).toMatch(/^Approved by you at \d{1,2}:\d{2}\s?[AP]M$/);
  });
});
