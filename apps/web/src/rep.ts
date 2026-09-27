// The human rep's view (I4): an explicit allow-list. The rep sees only what a
// counterparty can hear or has said: the agent's cp lines as heard, its own
// utterances, and the call opening and closing. Nothing else passes, and a line
// carries only the fields picked here, never the payload. The rep page reads its
// own server-filtered stream (/ws/rep); this filter is defence in depth.
import type { Ev } from "./replay";

export type RepLine = { seq: number; who: "agent" | "rep" | "call"; text: string };

export function repLine(e: Ev): RepLine | null {
  const p = e.payload;
  if (e.stream !== "agent" || e.actor !== "kernel" || p.lane !== "cp") return null;
  const line = (who: RepLine["who"], text: unknown): RepLine => ({ seq: e.seq, who, text: String(text ?? "") });
  if (e.type === "utt.delivered") return line("agent", `${String(p.text_heard ?? "")}${p.interrupted === true ? " [interrupted]" : ""}`);
  if (e.type === "utt.final" && p.speaker === "partner") return line("rep", p.text);
  if (e.type === "chan.opened") return line("call", "call connected");
  if (e.type === "chan.closed") return line("call", "call ended");
  return null;
}
