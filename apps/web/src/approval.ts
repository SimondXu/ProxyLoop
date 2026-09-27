// The approval card's state (I6), derived from events plus the outcome of this
// page's own POST. The kernel's approval.decided is the only decision; a 200
// means "sent", never "approved". Only the fixed emitters (ARCHITECTURE §4.1)
// move a card: nothing a model says or a user types changes it.
import { epochOf, from } from "./authority";
import type { PostResult } from "./liveApi";
import type { Ev } from "./replay";

/** contract/state.py ApprovalCard: the approval.requested payload. */
export type ApprovalCard = {
  approval_id: string;
  offer_ref: string;
  revision: number;
  terms_hash: string;
  readback_text: string;
  authority_epoch: number;
  expires_ms: number;
  binding: Record<string, unknown>;
};

export type Posting = "pending" | PostResult;
export type CardStatus =
  | "open"
  | "pending"
  | "sent"
  | "stale"
  | "superseded"
  | "already_decided"
  | "refused"
  | "granted"
  | "denied";
/** One read-back slot and its status (contract state.py ReadbackSlot.status). */
export type Slot = { field: string; status: string };
export type CardView = {
  seq: number;
  card: ApprovalCard;
  status: CardStatus;
  by: string | null;
  error: string | null;
  reason: string | null; // why: the kernel's refusal, a 409's reason, or the epoch
  slots: Slot[] | null; // the latest read-back of the card's offer revision, if any
};

/** The last Guard readback.updated{offer_ref, revision, slot_statuses} for this card's offer revision. */
export function readback(events: Ev[], card: ApprovalCard): Slot[] | null {
  const last = events.findLast(
    (e) => from(e, "readback.updated", ["guard"]) && e.payload.offer_ref === card.offer_ref && e.payload.revision === card.revision,
  );
  const statuses = last?.payload.slot_statuses;
  if (typeof statuses !== "object" || statuses === null) return null;
  return Object.entries(statuses).map(([field, status]) => ({ field, status: String(status) }));
}

export function approvalCards(events: Ev[], posts: ReadonlyMap<string, Posting>): CardView[] {
  const requested = events.filter((e) => from(e, "approval.requested", ["guard"]));
  const epoch = epochOf(events);
  return requested.map((req) => {
    const card = req.payload as ApprovalCard;
    const id = card.approval_id;
    const posting = posts.get(id);
    const result = posting === "pending" ? undefined : posting;
    const failed = result && !result.ok ? result : null;
    const why = failed?.reason && failed.reason !== failed.error ? `: ${failed.reason}` : ""; // not "already_decided: already_decided"
    const error = failed && `${failed.status ? `${failed.status} ` : ""}${failed.error}${why}`;
    const slots = readback(events, card);
    const view = (status: CardStatus, by: string | null = null, reason: string | null = null): CardView => ({
      seq: req.seq,
      card,
      status,
      by,
      error,
      reason,
      slots,
    });

    const decided = events.find((e) => from(e, "approval.decided", ["kernel"]) && e.payload.approval_id === id);
    if (decided) return view(decided.payload.decision as CardStatus, String(decided.payload.by));
    // The kernel re-decided a post and refused it, citing this card's approval.requested.
    const refused = events.find(
      (e) => from(e, "action.denied", ["kernel"]) && e.payload.intent === "approval.post" && e.cause_ids.includes(req.event_id),
    );
    if (refused) return view("refused", null, String(refused.payload.reason));
    if (requested.some((o) => o.seq > req.seq && o.payload.offer_ref === card.offer_ref)) return view("superseded");
    // A 409 says why (guard.decide's reason); only a moved epoch blames the epoch.
    if (failed?.status === 409 && (failed.error === "stale" || failed.error === "already_decided")) {
      return view(failed.error, null, failed.error === "stale" ? (failed.reason ?? null) : null);
    }
    if (epoch > card.authority_epoch) return view("stale", null, "the authority epoch moved past this card");
    if (posting === "pending") return view("pending");
    const posted = events.some(
      (e) => from(e, "approval.post", ["ui", "sim_approver"]) && e.payload.subject === "approval" && e.payload.subject_id === id,
    );
    if (posted || result?.ok) return view("sent");
    return view("open");
  });
}
