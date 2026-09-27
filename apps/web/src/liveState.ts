// Pure pieces of the live views: the WebSocket streams (/ws/live: one
// events.jsonl line per frame; /ws/rep: rebuilt frames, rep.ts), the per-lane
// model options, and which sent messages have not
// yet come back as events. The UI shows only what events say.
import { CLOSE } from "./liveApi";
import type { Ev } from "./replay";

export type Phase = "connecting" | "open" | "ended" | "closed" | "error";
export type Framed = { seq: number; type: string };
export type Stream<T extends Framed = Ev> = { events: T[]; next: number; phase: Phase; message: string };
export const start = <T extends Framed>(): Stream<T> => ({ events: [], next: 0, phase: "connecting", message: "" });
export const START: Stream = start<Ev>();

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);

/** A frame with a numeric seq, a string type and an object payload; otherwise an error string. */
export function parseFrame(text: string): Json | string {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    return "not JSON";
  }
  if (!isObject(v) || typeof v.seq !== "number" || typeof v.type !== "string" || !isObject(v.payload)) {
    return "no seq, type or payload";
  }
  return v;
}

/** A /ws/live frame: one events.jsonl line. */
export const parseEvent = (text: string) => parseFrame(text) as Ev | string;

/**
 * Accept one parsed frame (or a parse error). A seq below `next` is a duplicate
 * (a reconnect overlap) and is dropped. On a dense stream (/ws/live) a seq above
 * `next` is a gap: the stream stops with a visible error, never papered over.
 * The rep's filtered stream keeps original seqs and skips by design, so it only
 * has to increase.
 */
export function acceptFrame<T extends Framed>(s: Stream<T>, frame: T | string, dense: boolean): Stream<T> {
  if (s.phase === "error") return s;
  if (typeof frame === "string") return { ...s, phase: "error", message: `bad frame after seq ${s.next - 1}: ${frame}` };
  if (frame.seq < s.next) return s;
  if (dense && frame.seq > s.next) {
    return { ...s, phase: "error", message: `seq gap: expected ${s.next}, got ${frame.seq}` };
  }
  return { ...s, events: [...s.events, frame], next: frame.seq + 1 };
}

/** `entry` is where the viewer's role gets its cookies (liveApi.entry). */
export function closed<T extends Framed>(s: Stream<T>, code: number, reason: string, entry: string): Stream<T> {
  if (s.phase === "error") return s;
  const why = `${code}${reason ? ` ${reason}` : ""}`;
  if (code === CLOSE.ended) return { ...s, phase: "ended", message: `stream ended (${why})` };
  if (code === CLOSE.forbidden) {
    return { ...s, phase: "error", message: `not authorised (${why}): open ${entry} from this origin` };
  }
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
