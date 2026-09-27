// The operator's start page (?start; S1-SYS-33 shapes, serve/start.py): the
// options exactly as GET /api/models sends them, grouped by lane, and every
// refusal as a visible line. Nothing here invents, filters or relabels an
// option: an answer that breaks serve's promises is an error, never repaired.
import type { Failed } from "./liveApi";
import { isObject } from "./liveState";

export type LaneKey = "fast_user" | "fast_cp" | "slow";
export const START_LANES: { lane: LaneKey; title: string }[] = [
  { lane: "fast_user", title: "Fast-U" },
  { lane: "fast_cp", title: "Fast-C" },
  { lane: "slow", title: "Slow" },
];
/** serve.cases ModelOption. */
export type ModelOption = { id: string; lane: LaneKey; label: string; endpoint: string; model_id: string; default: boolean };
export type Offer = { options: ModelOption[]; tasks: string[] };

const TEXT = ["id", "label", "endpoint", "model_id"] as const;
const LANE_KEYS: unknown[] = START_LANES.map((l) => l.lane);

/** The /api/models body, or why it cannot be used. */
export function parseOffer(body: unknown): Offer | string {
  if (!isObject(body) || !Array.isArray(body.options) || !Array.isArray(body.tasks)) return "the answer is not {options, tasks}";
  if (!body.tasks.every((t) => typeof t === "string")) return "a task is not a string";
  for (const o of body.options as unknown[]) {
    const ok = isObject(o) && TEXT.every((k) => typeof o[k] === "string") && typeof o.default === "boolean" && LANE_KEYS.includes(o.lane);
    if (!ok) return `a malformed option: ${JSON.stringify(o)}`;
  }
  const options = body.options as ModelOption[];
  for (const { lane } of START_LANES) {
    const own = options.filter((o) => o.lane === lane);
    if (own.length > 0 && own.filter((o) => o.default).length !== 1) return `lane ${lane} does not have exactly one default`;
  }
  return { options, tasks: body.tasks as string[] };
}

/** Each lane's default option id (exactly one per lane that has options). */
export const defaults = (options: ModelOption[]): Record<string, string> =>
  Object.fromEntries(options.filter((o) => o.default).map((o) => [o.lane, o.id]));

const WHY: Record<string, string> = {
  unknown_task: "the kernel does not know this task",
  unknown_model: "the kernel does not know a chosen model",
  wrong_lane: "a chosen model belongs to another lane",
  not_live: "a chosen model cannot run live",
  busy: "a session is already running: wait for it to end",
  unavailable: "the kernel could not start the session; see the server log",
  csrf: "no valid operator cookie: open /start",
  origin: "the request came from another origin",
  "invalid body": "the server refused the form",
};

/** A refused start as one line: status, error, reason and what it means. */
export function startError(r: Failed): string {
  const head = `${r.status ? `${r.status} ` : ""}${r.error}${r.reason ? `: ${r.reason}` : ""}`;
  const why = WHY[r.reason ?? r.error];
  return why ? `${head} (${why})` : head;
}
