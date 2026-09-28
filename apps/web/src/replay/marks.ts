// The replay's pure parts (redesign §3.4): the PlaybackBar's markers and
// chapters, its clock, the frame cut-off, and a library row's date and chips.
// Markers come from timeline.ts's steps, which move only on fixed-emitter
// events; the outcome is the kernel's session.ended, where the receipt appears.
import { from } from "../authority";
import type { Ev } from "../replay";
import type { Step } from "../timeline";

export type MarkKind = "offer" | "approval" | "decision" | "fence" | "outcome";
export type Mark = { kind: MarkKind; t_ms: number; label: string };

// A step's kind (timeline.ts: the event type) → its marker. A fence step exists only for a stop you sent while
// something was waiting on the case; a decision is yours or the sim approver's, on an approval or on limits.
const KIND: Record<string, MarkKind> = {
  "offer.recorded": "offer",
  "approval.requested": "approval",
  "approval.decided": "decision",
  "mandate.decided": "decision",
  "authority.fence": "fence",
};
export const MARK_LABEL: Record<MarkKind, string> = {
  offer: "Offer",
  approval: "Approval asked",
  decision: "Decision",
  fence: "Paused by your message",
  outcome: "Outcome",
};

/** The markers, in time order. A merged step (a cleared fence) is marked where it began: its first event's t_ms. */
export function marks(events: Ev[], steps: Step[]): Mark[] {
  const at = new Map(events.map((e) => [e.seq, e.t_ms]));
  const out: Mark[] = [];
  for (const s of steps) {
    const kind = KIND[s.kind];
    if (kind) out.push({ kind, t_ms: at.get(s.seq) ?? s.t_ms, label: MARK_LABEL[kind] });
  }
  const ended = events.find((e) => from(e, "session.ended", ["kernel"]));
  if (ended) out.push({ kind: "outcome", t_ms: ended.t_ms, label: MARK_LABEL.outcome });
  return out.sort((a, b) => a.t_ms - b.t_ms);
}

export type Chapter = { name: string; t_ms: number | null };

/**
 * The four chapters (null: the run never got there). "Call starts" is the first call opening on the phone lane;
 * "Your decision" the first thing put to you: Guard's approval card or its proposed limits, whichever came first.
 */
export function chapters(steps: Step[], found: Mark[]): Chapter[] {
  const first = (kind: MarkKind) => found.find((m) => m.kind === kind)?.t_ms ?? null;
  const call = steps.find((s) => s.kind === "chan.opened");
  const asked = [first("approval"), ...steps.filter((s) => s.kind === "mandate.proposed").map((s) => s.t_ms)].filter((t) => t !== null);
  return [
    { name: "Call starts", t_ms: call ? call.t_ms : null },
    { name: "Offer", t_ms: first("offer") },
    { name: "Your decision", t_ms: asked.length > 0 ? Math.min(...asked) : null },
    { name: "Outcome", t_ms: first("outcome") },
  ];
}

/** Session time as mm:ss ("03:12"), from the run's start. */
export const mmss = (ms: number) => {
  const s = Math.floor(Math.max(0, ms) / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
};

/**
 * The frame's cut-off: the latest event time at or before `t` (-1 before the first). Frames with the same cut-off
 * show the same events, so the page re-derives only when an event enters or leaves. `times` ascending.
 */
export function cutoff(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((times[mid] ?? 0) <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo === 0 ? -1 : (times[lo - 1] ?? -1);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "27 Sep 2026, 08:56 UTC" from a run id's prefix (kernel new_run_id: 20260927T085615Z-…); null for any other id. */
export function runDate(runId: string): string | null {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})\d{2}Z-/.exec(runId);
  const month = m ? MONTHS[Number(m[2]) - 1] : undefined;
  if (!m || !month) return null;
  return `${Number(m[3])} ${month} ${m[1]}, ${m[4]}:${m[5]} UTC`;
}

/** A bundle under evidence/<stage>/: serve lists each such stage as a root, and /api/bundles sends the root's name. */
export const isEvidence = (root: string) => /^s\d+$/.test(root);

/** A run's page from the library; every other parameter (?view=engineer) is kept. */
export function runHref(search: string, runId: string): string {
  const q = new URLSearchParams(search);
  q.set("run", runId);
  return `?${q.toString()}`;
}
