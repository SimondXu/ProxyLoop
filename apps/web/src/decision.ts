// The approval card's words (redesign §3.2): its status, headline, the accept
// that follows a grant, and the progress after it. approval.ts keeps the state;
// this module only names it. Every input is a fixed-emitter event.
import type { CardStatus, CardView } from "./approval";
import { from } from "./authority";
import { grantOfAccept } from "./conversation";
import { inWords, type MandateView } from "./mandate";
import type { Ev } from "./replay";
import { clock, usd, whole, type TermRow } from "./terms";

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

/** Its price bound, as a label ("your limit $65.00"); never a difference. */
export function priceLimit(mandates: MandateView[]): string | null {
  const bound = current(mandates)?.mandate.max_monthly_price_minor;
  return bound == null ? null : `your limit ${usd(bound) ?? bound}`;
}

export function why(mandates: MandateView[]): string {
  const m = current(mandates);
  if (!m) return "You haven't set limits, so the agent needs your OK.";
  return `It's outside the limits ${m.by === "ui" ? "you" : "the simulated approver"} confirmed, so the agent can't say yes without you.`;
}

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
