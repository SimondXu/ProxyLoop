// The live page's authority strip (I6), derived from events only. The fixed
// emitters (contract events.py EMITTERS) gate what moves it: authority.* from
// kernel or guard, status.changed from guard. speak.revoked and action.denied
// are restrict-only, which any actor may emit, so the strip names the actor.
import type { Ev } from "./replay";

export const from = (e: Ev, type: string, actors: string[]) => e.type === type && actors.includes(e.actor);
const AUTHORITY = ["kernel", "guard"];

/** The current authority epoch: the max authority.epoch.new, else 0. */
export const epochOf = (events: Ev[]) =>
  Math.max(0, ...events.filter((e) => from(e, "authority.epoch", AUTHORITY)).map((e) => Number(e.payload.new)));

export type Strip = {
  status: string | null; // the latest status.changed.status
  fences: string[]; // raised and not cleared, by fence_id
  lastFence: { op: string; fence_id: string } | null;
  epoch: number;
  revoked: { reason: string; actor: string } | null; // the last speak.revoked
  denied: { intent: string; reason: string; actor: string } | null; // the last action.denied
};

export function authorityStrip(events: Ev[]): Strip {
  const s: Strip = { status: null, fences: [], lastFence: null, epoch: epochOf(events), revoked: null, denied: null };
  const open = new Set<string>();
  for (const e of events) {
    const p = e.payload;
    if (from(e, "status.changed", ["guard"])) s.status = String(p.status);
    else if (from(e, "authority.fence", AUTHORITY)) {
      const fence = { op: String(p.op), fence_id: String(p.fence_id) };
      if (fence.op === "raised") open.add(fence.fence_id);
      if (fence.op === "cleared") open.delete(fence.fence_id);
      s.lastFence = fence;
    } else if (e.type === "speak.revoked") s.revoked = { reason: String(p.reason), actor: e.actor };
    else if (e.type === "action.denied") s.denied = { intent: String(p.intent), reason: String(p.reason), actor: e.actor };
  }
  s.fences = [...open];
  return s;
}
