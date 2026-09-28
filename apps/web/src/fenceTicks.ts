// The chat's read receipts (redesign §3.2): every user.msg raises a fence whose
// utt_id is that message's event id (kernel/fence.py), and the fence clears once
// the agent has read it. Only the fixed emitters' authority.fence counts.
import { from } from "./authority";
import type { Ev } from "./replay";

export type Receipt = "pausing" | "read";

/** user.msg event id → its receipt; a message with no fence event (an older bundle) has none. */
export function receipts(events: Ev[]): Map<string, Receipt> {
  const open = new Map<string, Set<string>>(); // utt_id → raised, not cleared, fence ids
  for (const e of events) {
    if (!from(e, "authority.fence", ["kernel", "guard"])) continue;
    const utt = String(e.payload.utt_id);
    const fences = open.get(utt) ?? new Set<string>();
    if (e.payload.op === "raised") fences.add(String(e.payload.fence_id));
    if (e.payload.op === "cleared") fences.delete(String(e.payload.fence_id));
    open.set(utt, fences);
  }
  return new Map([...open].map(([utt, fences]) => [utt, fences.size > 0 ? "pausing" : "read"]));
}
