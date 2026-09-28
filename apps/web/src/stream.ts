// The Live stream (S1-SYS-77, prototype v4), a layout helper: in seq order, the chat's heard lines, the caller's
// items (the Guard cards, the receipt) and the call, one card per kernel chan.opened lane=cp, split into parts where
// a chat line or an item falls between two call lines. Every line is conversation.ts's (kernel events, heard text).
import { conversation, type Line } from "./conversation";
import type { Ev } from "./replay";
import { clock } from "./terms";

/** A call's part: `call` counts the kernel's chan.opened as callHead does (0: lines before any), `part` from 1; `ended`: it holds chan.closed. */
export type CallPart = { call: number; part: number; last: boolean; ended: boolean; lines: Line[] };
/** `time`: a centred time of day to show before the item, or null. */
export type Item<T> = { seq: number; time: string | null } & (
  | { kind: "line"; line: Line }
  | { kind: "item"; item: T }
  | { kind: "call"; part: CallPart }
);

// As the prototype: a time before the first item, then after 3 minutes or more (t_ms decides; wall is display only).
const GAP_MS = 180_000;

export function stream<T extends { seq: number }>(events: Ev[], items: T[]): Item<T>[] {
  const c = conversation(events);
  const bySeq = new Map(events.map((e) => [e.seq, e]));
  type In = { seq: number } & ({ kind: "line"; line: Line } | { kind: "item"; item: T } | { kind: "call"; line: Line });
  const all: In[] = [
    ...c.chat.map((line): In => ({ seq: line.seq, kind: "line", line })),
    ...items.map((item): In => ({ seq: item.seq, kind: "item", item })),
    ...c.call.map((line): In => ({ seq: line.seq, kind: "call", line })),
  ].sort((a, b) => a.seq - b.seq);

  const out: Item<T>[] = [];
  const parts: CallPart[] = [];
  let current: CallPart | null = null; // the part a next call line joins; any other item ends it
  let calls = 0;
  let shownAt: number | null = null;
  const push = (item: Item<T>) => {
    const e = bySeq.get(item.seq);
    const time = clock(e?.wall);
    if (e && time && (shownAt === null || e.t_ms - shownAt >= GAP_MS)) {
      item.time = time;
      shownAt = e.t_ms;
    }
    out.push(item);
  };
  for (const x of all) {
    if (x.kind !== "call") {
      current = null;
      push(x.kind === "line" ? { seq: x.seq, time: null, kind: "line", line: x.line } : { seq: x.seq, time: null, kind: "item", item: x.item });
      continue;
    }
    const type = bySeq.get(x.seq)?.type;
    if (type === "chan.opened") {
      calls += 1;
      current = null;
    }
    if (current === null) {
      const prev = parts.findLast((p) => p.call === calls);
      current = { call: calls, part: (prev?.part ?? 0) + 1, last: true, ended: false, lines: [] };
      if (prev) prev.last = false;
      parts.push(current);
      push({ seq: x.seq, time: null, kind: "call", part: current });
    }
    current.lines.push(x.line);
    if (type === "chan.closed") current.ended = true;
  }
  return out;
}
