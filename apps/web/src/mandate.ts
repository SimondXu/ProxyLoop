// The limits card's state (I6), the mandate twin of approval.ts: derived from
// Guard's mandate.proposed, the kernel's mandate.decided and authority.epoch,
// plus the outcome of this page's own POST (S1-SYS-41's route). A 200 means
// "sent", never "confirmed". Only the fixed emitters move a card.
import type { Posting } from "./approval";
import { epochOf, from } from "./authority";
import type { Ev } from "./replay";
import { clock, usd } from "./terms";

/** contract/state.py Mandate: the mandate.proposed payload. */
export type Mandate = {
  mandate_id: string;
  mandate_hash: string;
  epoch: number;
  max_monthly_price_minor?: number | null;
  max_term_months?: number | null;
  max_one_time_fees_minor?: number | null;
  required_features?: string[];
  forbidden_changes?: string[];
  expires_ms?: number | null;
};

export type MandateStatus =
  | ("open" | "pending" | "sent" | "granted" | "denied" | "superseded")
  | ("stale" | "already_decided" | "refused" | "tightened" | "withdrawn");
export type MandateView = {
  seq: number;
  mandate: Mandate;
  status: MandateStatus;
  by: string | null;
  at: string | null; // the decision's wall time, display only
  error: string | null;
  reason: string | null;
};

const AUTHORITY = ["kernel", "guard"];

export function mandateCards(events: Ev[], posts: ReadonlyMap<string, Posting>): MandateView[] {
  const proposed = events.filter((e) => from(e, "mandate.proposed", ["guard"]));
  const epoch = epochOf(events);
  return proposed.map((req) => {
    const m = req.payload as Mandate;
    const id = m.mandate_id;
    const posting = posts.get(id);
    const failed = posting && posting !== "pending" && !posting.ok ? posting : null;
    const why = failed?.reason && failed.reason !== failed.error ? `: ${failed.reason}` : "";
    const error = failed && `${failed.status ? `${failed.status} ` : ""}${failed.error}${why}`;
    const view = (status: MandateStatus, by: string | null = null, reason: string | null = null, at: string | null = null): MandateView =>
      ({ seq: req.seq, mandate: m, status, by, at, error, reason });
    const later = proposed.some((o) => o.seq > req.seq);

    const decided = events.find(
      (e) => from(e, "mandate.decided", ["kernel"]) && e.payload.mandate_id === id && e.payload.mandate_hash === m.mandate_hash,
    );
    if (decided) {
      const by = String(decided.payload.by);
      if (decided.payload.decision !== "granted") return view("denied", by, null, decided.wall ?? null);
      // Its own bump (mandate_decided) carries it; any later one ends it.
      const bumps = events.filter((e) => from(e, "authority.epoch", AUTHORITY) && e.seq > decided.seq);
      const own = bumps[0]?.payload.reason === "mandate_decided" ? 1 : 0;
      const end = bumps[own];
      if (end?.payload.reason === "tighten_mandate") return view("tightened", by);
      if (later || end) return view(later ? "superseded" : "withdrawn", by); // propose_mandate replaces it without a bump
      return view("granted", by, null, decided.wall ?? null);
    }
    const refused = events.find(
      (e) => from(e, "action.denied", ["kernel"]) && e.payload.intent === "approval.post" && e.cause_ids.includes(req.event_id),
    );
    if (refused) return view("refused", null, String(refused.payload.reason));
    if (later) return view("superseded");
    if (failed?.status === 409 && (failed.error === "stale" || failed.error === "already_decided")) {
      return view(failed.error, null, failed.error === "stale" ? (failed.reason ?? null) : null);
    }
    if (epoch > m.epoch) return view("stale", null, "epoch_moved");
    if (posting === "pending") return view("pending");
    const posted = events.some(
      (e) => from(e, "approval.post", ["ui", "sim_approver"]) && e.payload.subject === "mandate" && e.payload.subject_id === id,
    );
    return view(posted || posting?.ok ? "sent" : "open");
  });
}

/** Guard's refusal reasons in plain words (redesign §2.5: "epoch" is never shown); unknown ones as sent. */
export const REASON: Record<string, string> = {
  epoch_moved: "your instructions changed",
  "the authority epoch moved past this card": "your instructions changed",
  stale_epoch: "your instructions changed",
  card_expired: "the offer expired",
  approval_expired: "the offer expired",
  card_superseded: "a newer offer replaced it",
  no_pending_card: "it is no longer waiting for you",
  no_proposal: "these limits are no longer proposed",
  subject_hash_mismatch: "the terms changed",
  fence_raised: "your new message came first",
};
export const inWords = (reason: string | null) => (reason ? (REASON[reason] ?? reason) : null);

const SIM = "the simulated approver (not you)";
const WORDS: Record<MandateStatus, string> = {
  open: "Waiting for your confirmation",
  pending: "Sending…",
  sent: "Sent. Waiting for Guard to record it", // never "confirmed": only mandate.decided decides
  granted: `Confirmed by ${SIM}`,
  denied: `Declined by ${SIM}`,
  superseded: "Replaced by newer limits",
  stale: "No longer valid",
  already_decided: "Already handled",
  refused: "Not accepted by the system",
  tightened: "Tightened: the planner proposed stricter limits for you to confirm",
  withdrawn: "Withdrawn: these limits no longer let the agent say yes",
};

export function limitsStatusText(v: Pick<MandateView, "status" | "by" | "at" | "reason">): string {
  const time = clock(v.at);
  const words = inWords(v.reason);
  if (v.by === "ui" && v.status === "granted") return `Confirmed by you${time ? ` · ${time}` : ""}`;
  if (v.by === "ui" && v.status === "denied") return "You said these are not your limits";
  return `${WORDS[v.status]}${words && (v.status === "stale" || v.status === "refused") ? `: ${words}` : ""}`;
}

/** The limits as labels: each bound as sent, never combined with an offer (rule 13). */
export function limitRows(m: Mandate): [string, string][] {
  const rows: [string, string][] = [];
  if (m.max_monthly_price_minor != null) rows.push(["Monthly price", `up to ${usd(m.max_monthly_price_minor) ?? m.max_monthly_price_minor}`]);
  if (m.max_term_months != null) rows.push(["Contract", `up to ${m.max_term_months} months`]);
  if (m.max_one_time_fees_minor != null) rows.push(["One-time fees", `up to ${usd(m.max_one_time_fees_minor) ?? m.max_one_time_fees_minor}`]);
  if (m.required_features?.length) rows.push(["Must include", m.required_features.join(", ")]);
  if (m.forbidden_changes?.length) rows.push(["Must not change", m.forbidden_changes.join(", ")]);
  return rows;
}
