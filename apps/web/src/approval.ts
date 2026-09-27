// The approval card's state (I6), derived from events plus the outcome of this
// page's own POST. The kernel's approval.decided is the only decision; a 200
// means "sent", never "approved". Only the fixed emitters (ARCHITECTURE §4.1)
// move a card: nothing a model says or a user types changes it.
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
export type CardStatus = "open" | "pending" | "sent" | "stale" | "superseded" | "already_decided" | "granted" | "denied";
export type CardView = { seq: number; card: ApprovalCard; status: CardStatus; by: string | null; error: string | null };

const from = (e: Ev, type: string, actors: string[]) => e.type === type && actors.includes(e.actor);

export function approvalCards(events: Ev[], posts: ReadonlyMap<string, Posting>): CardView[] {
  const requested = events.filter((e) => from(e, "approval.requested", ["guard"]));
  const epoch = Math.max(
    0,
    ...events.filter((e) => from(e, "authority.epoch", ["kernel", "guard"])).map((e) => Number(e.payload.new)),
  );
  return requested.map((req) => {
    const card = req.payload as ApprovalCard;
    const id = card.approval_id;
    const posting = posts.get(id);
    const result = posting === "pending" ? undefined : posting;
    const failed = result && !result.ok ? result : null;
    const error = failed && (failed.status ? `${failed.status} ${failed.error}` : failed.error);
    const view = (status: CardStatus, by: string | null = null): CardView => ({ seq: req.seq, card, status, by, error });

    const decided = events.find((e) => from(e, "approval.decided", ["kernel"]) && e.payload.approval_id === id);
    if (decided) return view(decided.payload.decision as CardStatus, String(decided.payload.by));
    if (requested.some((o) => o.seq > req.seq && o.payload.offer_ref === card.offer_ref)) return view("superseded");
    if (epoch > card.authority_epoch) return view("stale");
    if (posting === "pending") return view("pending");
    const posted = events.some(
      (e) => from(e, "approval.post", ["ui", "sim_approver"]) && e.payload.subject === "approval" && e.payload.subject_id === id,
    );
    if (posted || result?.ok) return view("sent");
    if (failed?.status === 409 && (failed.error === "stale" || failed.error === "already_decided")) {
      return view(failed.error);
    }
    return view("open");
  });
}
