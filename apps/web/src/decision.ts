// The approval card's words (redesign §3.2): its status, headline, the accept
// that follows a grant, and the progress after it. approval.ts keeps the state;
// this module only names it. Every input is a fixed-emitter event.
import type { CardStatus, CardView } from "./approval";
import { from } from "./authority";
import { grantOfAccept } from "./conversation";
import { inWords, limitRows, type MandateView } from "./mandate";
import type { Ev } from "./replay";
import { clock, offerSlots, READBACK_CHIP, usd, whole, type OfferRev, type TermRow } from "./terms";

/** The decision's wall time, display only. */
const decidedAt = (events: Ev[], id: string) =>
  events.find((e) => from(e, "approval.decided", ["kernel"]) && e.payload.approval_id === id)?.wall ?? null;

const WORDS: Record<CardStatus, string> = {
  open: "Waiting for your decision",
  pending: "Sending your answer…",
  sent: "Sent. Waiting for Guard to record it", // never "approved": only approval.decided decides
  granted: "Approved by the simulated approver (not you)",
  denied: "Declined by the simulated approver (not you)",
  stale: "No longer valid",
  superseded: "Replaced by a newer offer card",
  already_decided: "Already handled",
  refused: "Not accepted by the system",
};

export function approvalStatusText(v: CardView, events: Ev[]): string {
  const words = inWords(v.reason);
  const time = clock(decidedAt(events, v.card.approval_id));
  if (v.by === "ui" && v.status === "granted") return `You approved${time ? ` · ${time}` : ""}`;
  if (v.by === "ui" && v.status === "denied") return "You declined";
  return `${WORDS[v.status]}${words && (v.status === "stale" || v.status === "refused") ? `: ${words}` : ""}`;
}

/** "Accept $78 a month for 24 months?", from the card's own rows. */
export function headline(rows: TermRow[]): string {
  const price = rows.find((r) => r.field === "monthly_price")?.value;
  const term = rows.find((r) => r.field === "term_months")?.value;
  if (!price) return "Accept this offer?";
  return `Accept ${whole(price)} a month${term ? ` for ${term}` : ""}?`;
}

// The mandate in force: granted and not superseded, tightened or withdrawn since.
const current = (mandates: MandateView[]) => mandates.findLast((v) => v.status === "granted");

/** "Your limit" for a term the mandate in force does not bound. */
export const NO_LIMIT = "no limit set";
// A term's bound, by the label limitRows gives it, so the card uses the limits card's own words.
const BOUND = new Map([
  ["monthly_price", "Monthly price"],
  ["term_months", "Contract"],
  ["fees_none", "One-time fees"],
]);
// Terms the mandate constrains only by a list: its text row ("Must include …", "Must not change …") carries it.
const LISTED = new Map([
  ["feature", "Must include"],
  ["applied_change", "Must not change"],
  ["changes_none", "Must not change"],
]);

/**
 * A card row with "Your limit" beside "This offer" (root ruling (a), S1-SYS-78): the
 * mandate in force's bound as limitRows words it, or NO_LIMIT; null with no granted
 * mandate. Never a verdict and never a difference: Guard alone judges the mandate.
 */
export type OfferRow = TermRow & { limit: string | null };

export function offerRows(rows: TermRow[], mandates: MandateView[]): OfferRow[] {
  const m = current(mandates)?.mandate;
  const bounds = new Map(m ? limitRows(m) : []);
  const limitOf = (field: string): string => {
    const kind = field.split(":")[0] ?? field;
    const bound = BOUND.get(kind);
    if (bound) return bounds.get(bound) ?? NO_LIMIT;
    if (kind === "fee" && bounds.has("One-time fees")) return "counts toward one-time fees";
    const listed = LISTED.get(kind);
    return listed && bounds.has(listed) ? `see “${listed}” below` : NO_LIMIT;
  };
  return rows.map((r) => ({ ...r, limit: m ? limitOf(r.field) : null }));
}

/** The mandate in force's list rows ("Must include …", "Must not change …"): text only, no bar, no verdict. */
export function limitTextRows(mandates: MandateView[]): [string, string][] {
  const m = current(mandates)?.mandate;
  return m ? limitRows(m).filter(([k]) => [...LISTED.values()].includes(k)) : [];
}

/** "Read back · 3 of 5": the rows Guard read back (READBACK_CHIP's "confirmed"), of all the card's rows. */
export const readbackCount = (rows: TermRow[]) =>
  `${READBACK_CHIP.confirmed} · ${rows.filter((r) => r.status === "confirmed").length} of ${rows.length}`;

/**
 * The limit bar, monthly price only: both amounts as text, and where each sits (per
 * cent) on a display scale from 0 to 1.2 × the larger, so position is proportional
 * to the amount and neither mark sits at an edge. No verdict and no difference.
 */
export type LimitBar = { limit: string; offer: string; limitAt: number; offerAt: number };

export function limitBar(events: Ev[], card: OfferRev, mandates: MandateView[]): LimitBar | null {
  const bound = current(mandates)?.mandate.max_monthly_price_minor;
  const raw = offerSlots(events, card)?.find((s) => s.field === "monthly_price")?.value;
  const offer = typeof raw === "string" && /^\d+$/.test(raw) ? Number(raw) : null;
  const [limitText, offerText] = [usd(bound), usd(offer)];
  if (bound == null || offer == null || !limitText || !offerText) return null;
  const top = Math.max(bound, offer) * 1.2;
  const at = (v: number) => (top > 0 ? (v / top) * 100 : 0);
  return { limit: whole(limitText), offer: whole(offerText), limitAt: at(bound), offerAt: at(offer) };
}

export function why(mandates: MandateView[]): string {
  const m = current(mandates);
  if (!m) return "You haven't set limits, so the agent needs your OK.";
  return `It's outside the limits ${m.by === "ui" ? "you" : "the simulated approver"} confirmed, so the agent can't say yes without you.`;
}

/** why()'s static sub-line (root copy ruling, S1-SYS-78): Guard, not the rows below, judges the mandate. */
export const GUARD_CHECKS = "Guard checks every term — price, term, fees, features and changes — not only the numbers shown below.";

/** GUARD_CHECKS only beside why()'s "outside the limits … confirmed" variant, i.e. with a granted mandate; else null. */
export const whyNote = (mandates: MandateView[]): string | null => (current(mandates) ? GUARD_CHECKS : null);

/** Guard's accept line after this card's grant: none yet, held, released, or revoked (why). */
export type Accept = { state: "none" | "held" | "released" | "revoked"; reason: string | null };

export function acceptOf(events: Ev[], v: CardView): Accept {
  const decided = events.find((e) => from(e, "approval.decided", ["kernel"]) && e.payload.approval_id === v.card.approval_id);
  if (!decided || decided.payload.decision !== "granted") return { state: "none", reason: null };
  // This card's accept: the grant behind it (conversation.ts grantOfAccept) is this card's own,
  // so with two granted cards an accept never attaches to the other one.
  const said = events.find(
    (e) => from(e, "speak.verbatim", ["guard"]) && e.payload.kind === "accept" && grantOfAccept(e, events)?.event_id === decided.event_id,
  );
  if (!said) return { state: "none", reason: null };
  const after = (type: string) => events.find((e) => from(e, type, ["kernel"]) && e.cause_ids.includes(said.event_id));
  if (after("speak.released")) return { state: "released", reason: null };
  const revoked = after("speak.revoked");
  return revoked ? { state: "revoked", reason: String(revoked.payload.reason) } : { state: "held", reason: null };
}

/** Who approved a granted card, for the receipt: "you" only on the kernel's grant by the UI. */
export function approvedBy(events: Ev[], v: CardView): string {
  if (v.by !== "ui") return v.by === "sim_approver" ? "Approved by the simulated approver (not you)" : `Approved by ${v.by ?? "unknown"}`;
  const time = clock(decidedAt(events, v.card.approval_id));
  return `Approved by you${time ? ` at ${time}` : ""}`;
}

/** After a grant, the case status in words (guard's status.changed); null otherwise. */
export const PROGRESS: Record<string, string> = {
  COMMIT_AUTHORIZED: "The agent is saying yes on the call…",
  COMMITTED: "Accepted on the call. Checking the simulated company's records…",
  EVIDENCE_PENDING: "Confirmation received. Verifying…",
};

export const PAUSED = "Paused: reading your new message before anything is accepted.";
export const STOPPED = "Stopped. The yes was never said to the rep.";
