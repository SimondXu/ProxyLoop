// Pure reading of a bundle's events (ARCHITECTURE §4): which lane an event
// belongs to, what a card shows, and which model spoke a Fast sentence. Events
// are the only input; nothing here renders or rebuilds prompt text.

export type Payload = Record<string, unknown>;
export type Ev = {
  seq: number;
  event_id: string;
  t_ms: number;
  type: string;
  actor: string;
  stream: "agent" | "world" | "ops";
  cause_ids: string[];
  payload: Payload;
};
export type Lane = "user" | "rep" | "fast_u" | "fast_c" | "slow" | "guard" | "world";

export const LANES: { id: Lane; title: string }[] = [
  { id: "user", title: "User chat" },
  { id: "rep", title: "Rep" },
  { id: "fast_u", title: "Fast-U" },
  { id: "fast_c", title: "Fast-C" },
  { id: "slow", title: "Slow" },
  { id: "guard", title: "Guard" },
  { id: "world", title: "World (god-view)" },
];

const AUTHORITY = new Set([
  "speak.released",
  "authority.fence",
  "authority.epoch",
  "approval.post",
  "approval.decided",
  "mandate.decided",
]);
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

function fastLane(e: Ev): Lane | null {
  const lane = str(e.payload.lane) ?? { "fast.user": "user", "fast.cp": "cp" }[e.actor];
  return lane === "user" ? "fast_u" : lane === "cp" ? "fast_c" : null;
}

/** The lane of an event, from its fields only; null for ops and bookkeeping. */
export function laneOf(e: Ev): Lane | null {
  const lane = str(e.payload.lane);
  if (e.stream === "world") return "world";
  if (e.stream === "ops") return null;
  if (e.type === "user.msg") return "user";
  if (e.type === "utt.final") return e.payload.speaker === "partner" ? "rep" : "fast_c";
  if (e.type === "utt.delivered" || e.type.startsWith("chan.")) {
    return lane === "user" ? "user" : lane === "cp" ? "rep" : null;
  }
  if (e.type.startsWith("fast.") || e.type === "s2f.voiced") return fastLane(e);
  if (e.type === "f2s.msg" || e.type === "s2f.msg" || e.type.startsWith("slow.")) return "slow";
  if (e.type === "llm.call") return e.actor === "slow" ? "slow" : fastLane(e);
  if (e.actor === "guard" || AUTHORITY.has(e.type)) return "guard";
  return null;
}

/** The one line a card shows: what was said, heard, decided or returned. */
export function summary(e: Ev): string {
  const p = e.payload;
  if (e.type === "utt.delivered") {
    return `${str(p.text_heard) ?? ""}${p.interrupted === true ? " [interrupted]" : ""}`;
  }
  if (e.type === "slow.tool") return `${str(p.name) ?? "?"}: ${str(p.result_text) ?? ""}`;
  if (e.type === "llm.call") {
    return `${str(p.role) ?? "?"} → ${str(p.served_model_echo) ?? "no echo"}${p.error ? ` error: ${String(p.error)}` : ""}`;
  }
  if (e.type === "f2s.msg" || e.type === "s2f.msg") {
    const facts = Array.isArray(p.facts) ? p.facts.map((f) => (f as unknown[]).join("=")).join("; ") : "";
    return [str(p.type), facts, str(p.text)].filter(Boolean).join(" · ");
  }
  for (const key of ["text", "status", "reason", "act", "to", "name"]) {
    const v = str(p[key]);
    if (v) return v;
  }
  return Array.isArray(p.violations) ? p.violations.join("; ") : "";
}

export type Index = { byId: Map<string, Ev>; callById: Map<string, Ev> };

export function indexEvents(events: Ev[]): Index {
  const callById = new Map<string, Ev>();
  for (const e of events) {
    const id = str(e.payload.call_id);
    if (e.type === "llm.call" && id) callById.set(id, e);
  }
  return { byId: new Map(events.map((e) => [e.event_id, e])), callById };
}

export type ModelLabel = { model: string; adapter: string };
const UNKNOWN: ModelLabel = { model: "unknown", adapter: "unknown" };

/** fast.sentence → its fast.turn (cause) → the turn's call_id → that llm.call. */
export function modelLabel(sentence: Ev, index: Index): ModelLabel {
  const turn = sentence.cause_ids.map((id) => index.byId.get(id)).find((e) => e?.type === "fast.turn");
  const callId = str(turn?.payload.call_id);
  const call = callId === undefined ? undefined : index.callById.get(callId);
  if (call === undefined) return UNKNOWN;
  const ref = call.payload.model_ref as Payload | undefined;
  return {
    model: str(call.payload.served_model_echo) ?? str(ref?.model_id) ?? "unknown",
    adapter: str(call.payload.adapter_kind) ?? "unknown",
  };
}

/** The prompts.jsonl records an event points at, by sha. */
export function shasOf(e: Ev): { label: string; sha: string }[] {
  if (e.type !== "llm.call" && e.type !== "fast.request") return [];
  return (["view_sha", "prompt_sha", "response_sha"] as const)
    .map((key) => ({ label: key.replace("_sha", ""), sha: str(e.payload[key]) ?? "" }))
    .filter((s) => s.sha !== "");
}

export function parseJsonl<T>(text: string): T[] {
  return text
    .split("\n")
    .filter((line) => line.trim() !== "")
    .map((line) => JSON.parse(line) as T);
}
