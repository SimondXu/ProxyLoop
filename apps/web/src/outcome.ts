// The status line and the outcome banner (S1-SYS-39), from fixed-emitter events
// only: status.changed and completion.decided from guard, session.ended from the
// kernel. "Verified complete" is said only on VERIFIED_COMPLETE (I6: only the
// evidence-bound verifier reaches a VERIFIED_* status); an unknown status or
// reason is shown raw, never hidden.
import { from } from "./authority";
import { SIM_REP, UNKNOWN_PARTIES } from "./conversation";
import { honesty } from "./provenance";
import type { Ev } from "./replay";

// contract/state.py CaseStatus, in plain words.
const STATUS: Record<string, string> = {
  INTAKE: "gathering details before the call",
  MANDATED: "limits confirmed; the call has not started",
  IN_CALL: "on the call",
  AWAITING_APPROVAL: "waiting for your approval",
  COMMIT_AUTHORIZED: "approved; the agent is accepting on the call",
  COMMITTED: "accepted on the call, not yet verified",
  EVIDENCE_PENDING: "confirmation received, being verified",
  NEEDS_REPLAN: "the last step did not go through; re-planning",
  VERIFIED_COMPLETE: "verified complete",
  VERIFIED_NO_DEAL: "verified: no deal was made",
  ESCALATED: "escalated to a person",
  ABANDONED: "abandoned: the call ended without a result",
  CLOSED_NO_ACTION: "closed: information only, no action taken",
};

// session.ended reasons (kernel/session.py, watchdog.py, slow/authority.py finish outcomes).
const REASON: Record<string, string> = {
  completed: "the agent reported it complete",
  no_deal: "no deal was made",
  info_only: "information only, no action taken",
  escalate: "escalated to a person",
  timeout: "the session timed out",
  abandoned: "the rep hung up",
  stopped: "stopped",
  llm_unavailable: "a model endpoint was unavailable",
  budget: "the spend limit was reached",
  error: "an error stopped the session",
};

export const statusWords = (status: string): string => STATUS[status] ?? status;
export const reasonWords = (reason: string): string => REASON[reason] ?? reason;

export type Outcome = {
  title: string;
  verified: boolean; // VERIFIED_COMPLETE only
  reason: string;
  status: string | null; // the last status.changed, raw
  verdict: string | null; // the last completion.decided, "ok" or "fail" with its reasons
};
export type StatusView = { line: string; outcome: Outcome | null };

export function statusView(events: Ev[]): StatusView {
  let status: string | null = null;
  let verdict: string | null = null;
  let reason: string | null = null;
  for (const e of events) {
    const p = e.payload;
    if (from(e, "status.changed", ["guard"])) status = String(p.status);
    else if (from(e, "completion.decided", ["guard"])) {
      const why = Array.isArray(p.reasons) && p.reasons.length > 0 ? ` (${p.reasons.join("; ")})` : "";
      verdict = `${String(p.verdict)}${why}`;
    } else if (from(e, "session.ended", ["kernel"])) reason = String(p.reason);
  }
  if (reason === null) {
    return { line: `Status: ${status === null ? "starting (no status yet)" : statusWords(status)}`, outcome: null };
  }
  const verified = status === "VERIFIED_COMPLETE";
  const title = verified
    ? "Verified complete"
    : status === "VERIFIED_NO_DEAL"
      ? "Verified: no deal was made"
      : `Ended: ${reasonWords(reason)}. Not verified complete.`;
  return { line: `Session ended: ${reasonWords(reason)}`, outcome: { title, verified, reason, status, verdict } };
}

// The receipt (redesign §3.2, S1-SYS-51): which variant session.ended closes on.
// Guard's terminal status comes first, then the kernel's reason. Only a
// VERIFIED_COMPLETE says "Verified"; an unknown status or reason is shown raw.
export type ReceiptKind = "verified" | "committed" | "no_deal" | "info_only" | "abandoned" | "stopped" | "endpoint" | "error" | "ended";

// Why a session stopped short (session.ended reasons).
const STOP: Record<string, string> = {
  timeout: "the session timed out",
  slow_step_cap: "the planner's step limit was reached",
  budget: "the spend limit was reached",
  stopped: "the session was stopped",
};
// Guard has recorded an accept on the call, but no verifier has confirmed it.
const UNVERIFIED_COMMIT = ["COMMITTED", "EVIDENCE_PENDING"];

export const ENDPOINT = "A model endpoint stopped responding, so the case stopped. ProxyLoop never switches to a backup model.";

export function receiptKind(o: Outcome): ReceiptKind {
  if (o.status === "VERIFIED_COMPLETE") return "verified";
  if (o.status === "VERIFIED_NO_DEAL") return "no_deal";
  if (o.status === "CLOSED_NO_ACTION") return "info_only";
  if (o.reason === "llm_unavailable") return "endpoint";
  if (o.reason === "error") return "error";
  if (o.status === "ABANDONED" || o.reason === "abandoned") return "abandoned";
  if (o.reason in STOP) return "stopped";
  if (o.status !== null && UNVERIFIED_COMMIT.includes(o.status)) return "committed";
  return "ended";
}

export function receiptTitle(kind: ReceiptKind, o: Outcome): string {
  return {
    verified: "Done. Verified.",
    committed: "Accepted on the call. Not verified yet.",
    no_deal: "No deal. Nothing was accepted.",
    info_only: "Here's what they offered · nothing accepted (information only)",
    abandoned: "The rep ended the call.",
    stopped: `Stopped: ${STOP[o.reason] ?? o.reason}. Not completed.`,
    endpoint: ENDPOINT,
    error: "An error stopped the case. Not completed.",
    ended: o.title,
  }[kind];
}

/**
 * A note when Guard recorded an accept that nothing verified, on a receipt whose title does not say so.
 * Any guard status.changed to COMMITTED or EVIDENCE_PENDING counts, not only the last: a hang-up moves
 * COMMITTED to ABANDONED.
 */
export function unverifiedCommit(kind: ReceiptKind, events: Ev[]): string | null {
  if (kind === "committed" || kind === "verified") return null;
  const committed = events.some((e) => from(e, "status.changed", ["guard"]) && UNVERIFIED_COMMIT.includes(String(e.payload.status)));
  return committed ? "The agent had accepted on the call; this was never verified." : null;
}

/** Whether the company on the call is simulated, by the honesty band's labels (provenance.ts); unknown parties count as simulated. */
export function simulatedCompany(events: Ev[]): boolean {
  const { sim } = honesty(events);
  return sim.includes(SIM_REP) || sim.includes(UNKNOWN_PARTIES);
}
export const verifiedAgainst = (simulated: boolean) => `Verified against the ${simulated ? "simulated " : ""}company's records`;

/** The verifier's line: Guard's last completion.decided, by its typed verdict ("ok" only); null otherwise. */
export function verifiedLine(events: Ev[]): string | null {
  const last = events.findLast((e) => from(e, "completion.decided", ["guard"]));
  return last?.payload.verdict === "ok" ? verifiedAgainst(simulatedCompany(events)) : null;
}

/** Guard's evidence.recorded confirmation ids, in order. */
export const confirmations = (events: Ev[]): string[] =>
  events.filter((e) => from(e, "evidence.recorded", ["guard"]) && typeof e.payload.confirmation_id === "string").map((e) => String(e.payload.confirmation_id));

/** session.ended.spend (kernel/session.py, SpendLedger.totals), formatted only: no sums, no savings (rule 13). */
export function spendLines(events: Ev[]): string[] {
  const end = events.findLast((e) => from(e, "session.ended", ["kernel"]));
  const s = end?.payload.spend;
  const none = ["No cost was recorded for this run."];
  if (typeof s !== "object" || s === null) return none;
  const { priced_micro_usd: priced, unpriced_calls: unpriced, gpu_time_calls: gpu } = s as Record<string, unknown>;
  const lines: string[] = [];
  if (priced != null) lines.push(`Priced model calls: ${typeof priced === "number" && Number.isInteger(priced) ? microUsd(priced) : String(priced)}`);
  if (typeof unpriced === "number" && unpriced > 0) lines.push(`${unpriced} call${unpriced === 1 ? "" : "s"} unpriced`);
  if (typeof gpu === "number" && gpu > 0) lines.push(`${gpu} GPU call${gpu === 1 ? "" : "s"}, billed by Modal and not counted here`);
  return lines.length > 0 ? lines : none;
}

/** Micro-USD as dollars, exact (six places at most); formatting only. */
export const microUsd = (micro: number): string =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 }).format(micro / 1_000_000);
