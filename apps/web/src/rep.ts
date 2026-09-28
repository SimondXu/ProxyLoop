// The human rep's view (I4): an explicit allow-list. The rep sees only what a
// counterparty can hear or has said: the agent's cp lines as heard, its own
// utterances, and the call opening and closing. Nothing else passes, and a line
// carries only the fields picked here, never the payload. The rep page reads its
// own server-filtered stream (/ws/rep); this filter is defence in depth.
import { parseFrame } from "./liveState";

/**
 * A /ws/rep frame, rebuilt by the server: {seq (the rep stream's own dense seq,
 * not the event's), t_ms (the event's), type, payload (allow-listed fields)},
 * with no actor or stream. A full event fits
 * this shape too, and then its actor and stream must match as well.
 */
export type RepFrame = {
  seq: number;
  t_ms: number;
  type: string;
  payload: Record<string, unknown>;
  actor?: string;
  stream?: string;
};

/** Keeps only the RepFrame fields of a frame. */
export function parseRepFrame(text: string): RepFrame | string {
  const v = parseFrame(text);
  if (typeof v === "string") return v;
  const payload = v.payload as RepFrame["payload"];
  const frame: RepFrame = { seq: v.seq as number, t_ms: Number(v.t_ms), type: v.type as string, payload };
  if ("actor" in v) frame.actor = String(v.actor);
  if ("stream" in v) frame.stream = String(v.stream);
  return frame;
}

export type RepLine = { seq: number; who: "agent" | "rep" | "call"; text: string };

export function repLine(e: RepFrame): RepLine | null {
  const p = e.payload;
  if (p.lane !== "cp") return null;
  if (e.actor !== undefined && e.actor !== "kernel") return null;
  if (e.stream !== undefined && e.stream !== "agent") return null;
  const line = (who: RepLine["who"], text: unknown): RepLine => ({ seq: e.seq, who, text: String(text ?? "") });
  if (e.type === "utt.delivered") return line("agent", `${String(p.text_heard ?? "")}${p.interrupted === true ? " [interrupted]" : ""}`);
  if (e.type === "utt.final" && p.speaker === "partner") return line("rep", p.text);
  if (e.type === "chan.opened") return line("call", "call connected");
  if (e.type === "chan.closed") return line("call", "call ended");
  return null;
}

/**
 * The call as the rep may speak in it: the latest chan.opened or chan.closed that passes the allow-list
 * (the kernel's, on the cp lane). "none" before any; the rep may speak only while it is "open".
 */
export function callState(frames: RepFrame[]): "none" | "open" | "ended" {
  const last = frames.findLast((e) => (e.type === "chan.opened" || e.type === "chan.closed") && repLine(e) !== null);
  return last === undefined ? "none" : last.type === "chan.opened" ? "open" : "ended";
}
