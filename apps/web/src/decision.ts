// The approval card's words (redesign §3.2): its status, headline, the accept
// that follows a grant, and the progress after it. approval.ts keeps the state;
// this module only names it. Every input is a fixed-emitter event.
import type { CardStatus, CardView } from "./approval";
import { from } from "./authority";
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

/** The latest granted mandate's price bound, as a label ("your limit $65.00"); never a difference. */
export function priceLimit(mandates: MandateView[]): string | null {
  const m = mandates.findLast((v) => v.status === "granted")?.mandate;
  const limit = m?.max_monthly_price_minor == null ? null : usd(m.max_monthly_price_minor);
  return limit && `your limit ${limit}`;
}

export const why = (mandates: MandateView[]) =>
  mandates.some((v) => v.status === "granted")
    ? "It's outside the limits you confirmed, so the agent can't say yes without you."
    : "You haven't set limits, so the agent needs your OK.";

/** Guard's accept line after this card's grant: none yet, held, released, or revoked (why). */
export type Accept = { state: "none" | "held" | "released" | "revoked"; reason: string | null };

export function acceptOf(events: Ev[], v: CardView): Accept {
  const decided = events.find((e) => from(e, "approval.decided", ["kernel"]) && e.payload.approval_id === v.card.approval_id);
  if (!decided || decided.payload.decision !== "granted") return { state: "none", reason: null };
  const said = events.find((e) => from(e, "speak.verbatim", ["guard"]) && e.payload.kind === "accept" && e.seq > decided.seq);
  if (!said) return { state: "none", reason: null };
  const after = (type: string) => events.find((e) => from(e, type, ["kernel"]) && e.cause_ids.includes(said.event_id));
  if (after("speak.released")) return { state: "released", reason: null };
  const revoked = after("speak.revoked");
  return revoked ? { state: "revoked", reason: String(revoked.payload.reason) } : { state: "held", reason: null };
}

/** After a grant, the case status in words (guard's status.changed); null otherwise. */
export const PROGRESS: Record<string, string> = {
  COMMIT_AUTHORIZED: "The agent is saying yes on the call…",
  COMMITTED: "Accepted on the call. Checking the company's records…",
  EVIDENCE_PENDING: "Confirmation received. Verifying…",
};

export const PAUSED = "Paused: reading your new message before anything is accepted.";
export const STOPPED = "Stopped. The yes was never said to the rep.";
