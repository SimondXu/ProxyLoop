// The phase stepper (redesign §3.0), display only: from Guard's status.changed
// and the kernel's session.ended, nothing else. A step passed without its
// status is "skipped" (e.g. a call opened without limits); an unknown status is
// shown raw, never hidden, and the last known step stays current.
import { from } from "./authority";
import type { Ev } from "./replay";

export const STEPS = ["Details", "Limits", "On the call", "Your decision", "Result"] as const;
const RESULT = STEPS.length - 1;

// contract/state.py CaseStatus → the step it makes current.
const STEP: Record<string, number> = {
  INTAKE: 0,
  MANDATED: 1,
  IN_CALL: 2,
  NEEDS_REPLAN: 2,
  AWAITING_APPROVAL: 3,
  COMMIT_AUTHORIZED: RESULT,
  COMMITTED: RESULT,
  EVIDENCE_PENDING: RESULT,
  VERIFIED_COMPLETE: RESULT,
  VERIFIED_NO_DEAL: RESULT,
  ESCALATED: RESULT,
  ABANDONED: RESULT,
  CLOSED_NO_ACTION: RESULT,
};

export type StepState = "done" | "current" | "skipped" | "todo";
export type Phase = { steps: { label: string; state: StepState }[]; note: string | null; raw: string | null };

export function phase(events: Ev[]): Phase {
  const seen = new Set<number>([0]); // INTAKE is the case's first status, emitted or not
  let at = 0;
  let last: string | null = null;
  let ended = false;
  for (const e of events) {
    if (from(e, "session.ended", ["kernel"])) ended = true;
    if (!from(e, "status.changed", ["guard"])) continue;
    last = String(e.payload.status);
    const step = STEP[last];
    if (step === undefined) continue;
    at = step;
    seen.add(step);
  }
  if (ended) at = RESULT;
  const state = (i: number): StepState => (i === at ? "current" : i > at ? "todo" : seen.has(i) ? "done" : "skipped");
  return {
    steps: STEPS.map((label, i) => ({ label, state: state(i) })),
    note: last === "EVIDENCE_PENDING" && !ended ? "verifying…" : null,
    raw: last !== null && !Object.hasOwn(STEP, last) ? last : null,
  };
}
