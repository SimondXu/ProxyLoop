// The web's one data seam: the replay API's GETs (S1-SYS-09 shapes). In dev and
// preview, Vite serves them from PL_BUNDLE_DIR (server/bundleApi.ts); the real
// API is a base-URL/proxy change, never a second client.
import { parseJsonl, type Ev } from "./replay";

export type BundleInfo = { run_id: string; root: string; complete: boolean; task_ref: string | null };
export type PromptRecord = { sha: string; kind: "view" | "prompt" | "messages" | "response"; content: string };
export type Run = { events: Ev[] }; // the web reads events only (AGENTS rule 7)

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

async function get(path: string): Promise<Response>;
async function get(path: string, missing: null): Promise<Response | null>;
async function get(path: string, missing?: null): Promise<Response | null> {
  const res = await fetch(`${BASE}${path}`);
  if (res.status === 404 && missing === null) return null;
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
  return res;
}

const replay = (runId: string, rest: string) => `/api/replay/${encodeURIComponent(runId)}/${rest}`;

export async function listBundles(): Promise<BundleInfo[]> {
  const body = (await (await get("/api/bundles")).json()) as { bundles: BundleInfo[] };
  return body.bundles;
}

export async function loadRun(runId: string): Promise<Run> {
  const events = parseJsonl<Ev>(await (await get(replay(runId, "events"))).text());
  return { events: events.sort((a, b) => a.seq - b.seq) };
}

/** One prompts.jsonl record, verbatim; null when the bundle has none for this sha. */
export async function loadPrompt(runId: string, sha: string): Promise<PromptRecord | null> {
  const res = await get(replay(runId, `prompts/${encodeURIComponent(sha)}`), null);
  return res ? ((await res.json()) as PromptRecord) : null;
}
