// The conversation view (S1-SYS-39): who said what, as the listener heard it,
// read from events only. The chat is user.msg (You) and the user lane's
// utt.delivered (Assistant); the call is the cp lane's utt.delivered (Agent),
// the partner's utt.final (Rep) and the call's opening and closing. Only the
// kernel emits these (contract EMITTERS), so no other actor's event is shown.
// A delivery shows text_heard, never text_generated. A delivery released from
// Guard's speak.verbatim carries that line's fixed-wording tag.
import { from } from "./authority";
import type { Ev } from "./replay";

export type Speaker = "you" | "assistant" | "agent" | "rep" | "call";
/** `id` is the event id (a user.msg's is its fences' utt_id); `tag` is the Guard wording's label. */
export type Line = { seq: number; id: string; who: Speaker; text: string; interrupted: boolean; tag: string | null };
export type Conversation = { chat: Line[]; call: Line[] };

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** A delivery's Guard verbatim line: utt.delivered ← speak.released (kernel) ← speak.verbatim (guard). */
function verbatimOf(e: Ev, byId: Map<string, Ev>): Ev | null {
  for (const released of e.cause_ids.map((id) => byId.get(id))) {
    if (!released || !from(released, "speak.released", ["kernel"])) continue;
    const said = released.cause_ids.map((id) => byId.get(id)).find((v) => v && from(v, "speak.verbatim", ["guard"]));
    if (said) return said;
  }
  return null;
}

const TAG: Record<string, string> = {
  disclosure: "AI disclosure · fixed wording",
  readback_request: "Read-back request · fixed wording",
  decline: "Decline · fixed wording",
};
const BY: Record<string, string> = { ui: "approved by you", sim_approver: "approved by the simulated approver" };

/**
 * The kernel grant behind Guard's accept line: its capability (Guard's
 * action.authorized, same cap_id) → the approval cards with that terms_hash and
 * authority epoch → the kernel's last grant of one of them before the
 * authorization. null for an accept under your limits (no such grant).
 */
export function grantOfAccept(said: Ev, events: Ev[]): Ev | null {
  const cap = (e: Ev) => (e.payload.capability ?? {}) as { cap_id?: unknown; terms_hash?: unknown; epoch?: unknown };
  const capId = said.payload.cap_id;
  const auth = typeof capId === "string" ? events.find((e) => from(e, "action.authorized", ["guard"]) && cap(e).cap_id === capId) : undefined;
  const { terms_hash, epoch } = auth ? cap(auth) : {};
  if (!auth || typeof terms_hash !== "string" || typeof epoch !== "number") return null;
  const cards = events.filter((e) => from(e, "approval.requested", ["guard"]) && e.payload.terms_hash === terms_hash && e.payload.authority_epoch === epoch);
  const ids = new Set(cards.map((e) => e.payload.approval_id));
  const granted = (e: Ev) => from(e, "approval.decided", ["kernel"]) && e.payload.decision === "granted" && ids.has(e.payload.approval_id);
  return events.filter((e) => e.seq < auth.seq && granted(e)).at(-1) ?? null;
}

/** The accept's approver (grantOfAccept); an accept under your limits says only "fixed wording". */
function acceptedBy(said: Ev, events: Ev[]): string {
  const grant = grantOfAccept(said, events);
  return (grant && BY[str(grant.payload.by)]) ?? "fixed wording";
}

function tagOf(said: Ev, events: Ev[]): string {
  const kind = str(said.payload.kind);
  if (kind === "accept") return `Acceptance · ${acceptedBy(said, events)}`;
  return TAG[kind] ?? `${kind} · fixed wording`; // an unknown kind is shown raw
}

export function conversation(events: Ev[]): Conversation {
  const byId = new Map(events.map((e) => [e.event_id, e]));
  const out: Conversation = { chat: [], call: [] };
  for (const e of events) {
    if (e.actor !== "kernel" || e.stream !== "agent") continue;
    const p = e.payload;
    const line = (who: Speaker, text: string, interrupted = false, tag: string | null = null): Line => ({
      seq: e.seq,
      id: e.event_id,
      who,
      text,
      interrupted,
      tag,
    });
    if (e.type === "user.msg") out.chat.push(line("you", str(p.text)));
    else if (e.type === "utt.delivered" && p.lane === "user") out.chat.push(line("assistant", str(p.text_heard), p.interrupted === true));
    else if (e.type === "utt.delivered" && p.lane === "cp") {
      const said = verbatimOf(e, byId);
      out.call.push(line("agent", str(p.text_heard), p.interrupted === true, said && tagOf(said, events)));
    } else if (e.type === "utt.final" && p.lane === "cp" && p.speaker === "partner") out.call.push(line("rep", str(p.text)));
    else if (e.type === "chan.opened" && p.lane === "cp") out.call.push(line("call", "call connected"));
    else if (e.type === "chan.closed" && p.lane === "cp") out.call.push(line("call", "call ended"));
  }
  return out;
}

/** Which parties the world simulates, from the roles session.started names (kernel _roles). */
export type Parties = { known: boolean; simUser: boolean; simRep: boolean };

export function parties(events: Ev[]): Parties {
  const start = events.find((e) => e.type === "session.started" && e.actor === "kernel");
  const models = start?.payload.models;
  const roles = typeof models === "object" && models !== null ? Object.keys(models) : [];
  return { known: start !== undefined, simUser: roles.includes("simuser"), simRep: roles.includes("ear") || roles.includes("mouth") };
}

export const SIM_REP = "Simulated rep; no real company was called";
export const SIM_USER = "Simulated user";
export const UNKNOWN_PARTIES = "Parties not known yet (no session.started)";

/** The sim labels shown on every frame (I8, I11). */
export function simLabels(p: Parties): string[] {
  if (!p.known) return [UNKNOWN_PARTIES];
  return [...(p.simRep ? [SIM_REP] : []), ...(p.simUser ? [SIM_USER] : [])];
}

export function speakerName(who: Speaker, p: Parties): string {
  if (who === "you") return p.simUser ? "User (simulated)" : "You";
  if (who === "rep") return p.simRep ? "Rep (simulated)" : "Rep";
  return { assistant: "Assistant", agent: "Agent", call: "Call" }[who];
}

/** The call's header state: calls opened so far, whether one is open, and since when (t_ms) the rep is on hold. */
export type CallHead = { calls: number; open: boolean; holdSince: number | null };

/**
 * The hold follows the kernel's fold (core/fold.py cp_hold): FastC's chan.hold
 * with a reason sets it, one with reason null clears it, and so does the call's
 * opening or end. The same turn's speech comes after its chan.hold, so a heard
 * line does not end a hold.
 */
export function callHead(events: Ev[]): CallHead {
  const h: CallHead = { calls: 0, open: false, holdSince: null };
  for (const e of events) {
    const p = e.payload;
    if (p.lane !== "cp") continue;
    if (from(e, "chan.opened", ["kernel"])) Object.assign(h, { calls: h.calls + 1, open: true, holdSince: null });
    else if (from(e, "chan.closed", ["kernel"])) Object.assign(h, { open: false, holdSince: null });
    else if (from(e, "chan.hold", ["fast.cp"])) h.holdSince = p.reason == null ? null : e.t_ms;
  }
  return h;
}
