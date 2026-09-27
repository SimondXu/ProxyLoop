// Pure pieces of the live views: the WebSocket event stream (one events.jsonl
// line per frame), the per-lane model options, and which sent messages have not
// yet come back as events. The UI shows only what events say.
import { CLOSE } from "./liveApi";
import type { Ev } from "./replay";

export type Phase = "connecting" | "open" | "ended" | "closed" | "error";
export type Stream = { events: Ev[]; next: number; phase: Phase; message: string };
export const START: Stream = { events: [], next: 0, phase: "connecting", message: "" };

/**
 * Accept one frame. A seq below `next` is a duplicate (a reconnect overlap) and
 * is dropped. On a dense stream (/ws/live) a seq above `next` is a gap: the
 * stream stops with a visible error, never papered over. The rep's filtered
 * stream skips seqs by design, so it only has to increase.
 */
export function acceptFrame(s: Stream, text: string, dense: boolean): Stream {
  if (s.phase === "error") return s;
  let e: Ev;
  try {
    e = JSON.parse(text) as Ev;
  } catch {
    return { ...s, phase: "error", message: `bad frame after seq ${s.next - 1}: not JSON` };
  }
  if (typeof e?.seq !== "number" || typeof e.type !== "string") {
    return { ...s, phase: "error", message: `bad frame after seq ${s.next - 1}: no seq or type` };
  }
  if (e.seq < s.next) return s;
  if (dense && e.seq > s.next) return { ...s, phase: "error", message: `seq gap: expected ${s.next}, got ${e.seq}` };
  return { ...s, events: [...s.events, e], next: e.seq + 1 };
}

export function closed(s: Stream, code: number, reason: string): Stream {
  if (s.phase === "error") return s;
  const why = `${code}${reason ? ` ${reason}` : ""}`;
  if (code === CLOSE.ended) return { ...s, phase: "ended", message: `stream ended (${why})` };
  if (code === CLOSE.unknownRun) return { ...s, phase: "error", message: `unknown run (${why})` };
  if (code === CLOSE.badStream) return { ...s, phase: "error", message: `server: seq gap or bad line (${why})` };
  return { ...s, phase: "closed", message: `disconnected (${why})` };
}

export const MODEL_LANES = [
  { role: "fast_user", title: "Fast-U" },
  { role: "fast_cp", title: "Fast-C" },
  { role: "slow", title: "Slow" },
] as const;

type Refs = Record<string, { ref?: { kind?: unknown; model_id?: unknown } }>;

/** The session's real_http model ids (session.started models): the only dropdown options. */
export function realHttpModels(events: Ev[]): { options: string[]; configured: Record<string, string> } {
  const start = events.find((e) => e.type === "session.started");
  const models = Object.entries((start?.payload.models ?? {}) as Refs);
  const configured: Record<string, string> = {};
  for (const [role, m] of models) {
    if (m.ref?.kind === "real_http" && typeof m.ref.model_id === "string") configured[role] = m.ref.model_id;
  }
  return { options: [...new Set(Object.values(configured))], configured };
}

export type Sent = { text: string; after: number };

/** Sent texts that no event has echoed yet (each echo, seq ≥ after, matches one send). */
export function unechoed(sent: Sent[], echoes: { seq: number; text: string }[]): Sent[] {
  const used = new Set<number>();
  return sent.filter((s) => {
    const hit = echoes.find((e) => !used.has(e.seq) && e.seq >= s.after && e.text === s.text);
    if (hit) used.add(hit.seq);
    return !hit;
  });
}
