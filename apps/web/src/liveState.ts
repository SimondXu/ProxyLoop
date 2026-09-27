// Pure pieces of the live views: the WebSocket streams (/ws/live: one
// events.jsonl line per frame; /ws/rep: rebuilt frames with their own seq, rep.ts), the per-lane
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
export const parseEvent = (text: string): Ev | string => {
  const v = parseFrame(text);
  return typeof v === "string" ? v : (v as Ev);
};

/**
 * Accept one parsed frame (or a parse error). Both streams are dense from 0
 * (/ws/live: the event seq; /ws/rep: the rep stream's own seq). A seq below
 * `next` is a duplicate (a reconnect overlap) and is dropped; a seq above it is
 * a gap: the stream stops with a visible error, never papered over.
 */
export function acceptFrame<T extends Framed>(s: Stream<T>, frame: T | string): Stream<T> {
  if (s.phase === "error") return s;
  if (typeof frame === "string") return { ...s, phase: "error", message: `bad frame after seq ${s.next - 1}: ${frame}` };
  if (frame.seq < s.next) return s;
  if (frame.seq > s.next) return { ...s, phase: "error", message: `seq gap: expected ${s.next}, got ${frame.seq}` };
  return { ...s, events: [...s.events, frame], next: frame.seq + 1 };
}

/** `entry` is where the viewer's role gets its cookies (liveApi.entry). */
export function closed<T extends Framed>(s: Stream<T>, code: number, reason: string, entry: string): Stream<T> {
  if (s.phase === "error") return s;
  const why = `${code}${reason ? ` ${reason}` : ""}`;
  if (code === CLOSE.ended) return { ...s, phase: "ended", message: `stream ended (${why})` };
  // 1006 before the socket ever opened: the server refused the upgrade (a foreign or
  // missing Origin) or could not be reached; the browser cannot tell which.
  if (code === CLOSE.abnormal && s.phase === "connecting") {
    return {
      ...s,
      phase: "error",
      message: `refused or unreachable: check the API is running, then open ${entry} from this origin`,
    };
  }
  if (code === CLOSE.forbidden) {
    return { ...s, phase: "error", message: `not authorised (${why}): open ${entry} from this origin` };
  }
  if (code === CLOSE.unknownRun) return { ...s, phase: "error", message: `unknown run (${why})` };
  if (code === CLOSE.badStream) return { ...s, phase: "error", message: `server: seq gap or bad line (${why})` };
  return { ...s, phase: "closed", message: `disconnected (${why})` };
}

const FAST = ["fast_user", "fast_cp"];
/** Each lane's role, and the roles whose real_http models it may offer (never a world role). */
export const MODEL_LANES = [
  { role: "fast_user", title: "Fast-U", from: FAST },
  { role: "fast_cp", title: "Fast-C", from: FAST },
  { role: "slow", title: "Slow", from: ["slow"] },
] as const;

type Ref = { kind?: unknown; model_id?: unknown };
export type LaneModels = {
  role: string;
  title: string;
  options: string[];
  running: string | null;
  placeholder: string | null;
};

/**
 * The per-lane dropdowns, from session.started models only. A lane whose own
 * model is not real_http shows a disabled placeholder naming what it runs, never
 * another model; otherwise it offers the real_http ids of its `from` roles.
 */
export function laneModels(events: Ev[]): LaneModels[] {
  const start = events.find((e) => e.type === "session.started");
  const refs = (start?.payload.models ?? {}) as Record<string, { ref?: Ref }>;
  const real = (role: string) => {
    const ref = refs[role]?.ref;
    return ref?.kind === "real_http" && typeof ref.model_id === "string" ? ref.model_id : null;
  };
  return MODEL_LANES.map(({ role, title, from }) => {
    const running = real(role);
    if (running === null) {
      const ref = refs[role]?.ref;
      const what = ref ? `${String(ref.model_id)} (${String(ref.kind)})` : "no model";
      return { role, title, options: [], running, placeholder: `${what}: not selectable` };
    }
    const options = [...new Set(from.map(real).filter((id) => id !== null))];
    return { role, title, options, running, placeholder: null };
  });
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
