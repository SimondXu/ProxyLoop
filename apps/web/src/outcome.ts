// The status line and the outcome banner (S1-SYS-39), from fixed-emitter events
// only: status.changed and completion.decided from guard, session.ended from the
// kernel. "Verified complete" is said only on VERIFIED_COMPLETE (I6: only the
// evidence-bound verifier reaches a VERIFIED_* status); an unknown status or
// reason is shown raw, never hidden.
import { from } from "./authority";
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
