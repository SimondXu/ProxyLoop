// The conversation view (S1-SYS-39): who said what, as the listener heard it,
// read from events only. The chat is user.msg (You) and the user lane's
// utt.delivered (Assistant); the call is the cp lane's utt.delivered (Agent),
// the partner's utt.final (Rep) and the call's opening and closing. Only the
// kernel emits these (contract EMITTERS), so no other actor's event is shown.
// A delivery shows text_heard, never text_generated.
import { from } from "./authority";
import type { Ev } from "./replay";

export type Speaker = "you" | "assistant" | "agent" | "rep" | "call";
export type Line = { seq: number; who: Speaker; text: string; interrupted: boolean; disclosure: boolean };
export type Conversation = { chat: Line[]; call: Line[] };

const str = (v: unknown): string => (typeof v === "string" ? v : "");

/** A delivery's Guard verbatim kind: utt.delivered ← speak.released (kernel) ← speak.verbatim (guard). */
function verbatimKind(e: Ev, byId: Map<string, Ev>): string | null {
  for (const released of e.cause_ids.map((id) => byId.get(id))) {
    if (!released || !from(released, "speak.released", ["kernel"])) continue;
    const said = released.cause_ids.map((id) => byId.get(id)).find((v) => v && from(v, "speak.verbatim", ["guard"]));
    if (said) return str(said.payload.kind);
  }
  return null;
}

export function conversation(events: Ev[]): Conversation {
  const byId = new Map(events.map((e) => [e.event_id, e]));
  const out: Conversation = { chat: [], call: [] };
  for (const e of events) {
    if (e.actor !== "kernel" || e.stream !== "agent") continue;
    const p = e.payload;
    const line = (who: Speaker, text: string, interrupted = false, disclosure = false): Line => ({
      seq: e.seq,
      who,
      text,
      interrupted,
      disclosure,
    });
    if (e.type === "user.msg") out.chat.push(line("you", str(p.text)));
    else if (e.type === "utt.delivered" && p.lane === "user") out.chat.push(line("assistant", str(p.text_heard), p.interrupted === true));
    else if (e.type === "utt.delivered" && p.lane === "cp") {
      out.call.push(line("agent", str(p.text_heard), p.interrupted === true, verbatimKind(e, byId) === "disclosure"));
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
