// The approval card's hold line ("The rep is holding · 0:54"), display only: it
// counts up on the kernel clock (t_ms) from the call's hold start (callHead, the
// FastC chan.hold). Nothing acts on it: no expiry, no countdown, no disable.
import { callHead } from "./conversation";
import type { Ev } from "./replay";

/**
 * A live page's hold, in ms, or null with no hold. The hold that applies is the
 * call's current one (callHead.holdSince). "Now" is the latest event's t_ms, plus
 * `sinceLatest`: the local ms since that event arrived (display only).
 */
export function holdElapsed(events: Ev[], sinceLatest = 0): number | null {
  const since = callHead(events).holdSince;
  if (since === null) return null;
  const latest = events.reduce((t, e) => Math.max(t, e.t_ms), since);
  return Math.max(0, latest + sinceLatest - since);
}

/**
 * A replay's hold at playback time `t` (the recorded t_ms clock), or null with no hold:
 * `events` are those shown at `t`. It moves with playback between events, stands still
 * when paused, and never reads the viewer's clock.
 */
export function holdElapsedAt(events: Ev[], t: number): number | null {
  const since = callHead(events).holdSince;
  return since === null ? null : Math.max(0, t - since);
}

/** Elapsed ms as "m:ss" (whole seconds, rounded down). */
export function mmss(ms: number): string {
  const s = Math.floor(Math.max(0, ms) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
