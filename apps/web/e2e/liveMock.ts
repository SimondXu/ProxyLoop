// Mock event streams and endpoint captures for the live e2e specs. Events are
// built here (never copied from real bundles); the shapes follow liveApi.ts.
import type { Page, WebSocketRoute } from "@playwright/test";

export const RUN = "run-live-1";
export const CSRF = "csrf-e2e-token";
export const REP_CSRF = "rep-csrf-e2e-token";

/** An event factory with its own seq counter; `skip` leaves seqs out to fake a gap. */
export function events(runId = RUN) {
  let seq = 0;
  return (type: string, actor: string, payload: Record<string, unknown> = {}, opts: { stream?: string; skip?: number } = {}) => {
    seq += opts.skip ?? 0;
    const e = {
      schema: "pl.event/2",
      run_id: runId,
      seq,
      event_id: `${runId}:${seq}`,
      t_ms: seq * 100,
      wall: "2026-09-26T00:00:00Z",
      type,
      actor,
      stream: opts.stream ?? "agent",
      cause_ids: [],
      epoch: 0,
      payload,
    };
    seq += 1;
    return JSON.stringify(e);
  };
}

/** /ws/rep frames as S1-SYS-10 rebuilds them: {seq (the rep stream's own, dense), t_ms, type, payload}; `skip` fakes a gap. */
export function repFrames() {
  let seq = 0;
  return (type: string, payload: Record<string, unknown>, skip = 0) => {
    seq += skip;
    const frame = { seq, t_ms: seq * 100, type, payload };
    seq += 1;
    return JSON.stringify(frame);
  };
}

export const models = (refs: Record<string, [kind: string, modelId: string]>) =>
  Object.fromEntries(Object.entries(refs).map(([role, [kind, model_id]]) => [role, { ref: { kind, endpoint: null, model_id } }]));

export const started = (refs: Record<string, [string, string]>) => ({
  cfg_hash: "c",
  task_ref: "e2e@1",
  instance_hash: "i",
  split: "train",
  models: models(refs),
  renderer_fp: {},
  contract_version: "v1",
  git_sha: "g",
  attest: null,
  parity: "not_applicable",
});

/** Every WebSocket the page opens is mocked; `urls` records them, `connected` is the first. */
export async function mockSockets(page: Page) {
  const urls: string[] = [];
  let first: (ws: WebSocketRoute) => void = () => undefined;
  const connected = new Promise<WebSocketRoute>((resolve) => (first = resolve));
  await page.routeWebSocket(/\/ws\//, (ws) => {
    urls.push(ws.url());
    first(ws);
  });
  return { urls, connected };
}

export type Captured = { method: string; path: string; body: unknown; csrf: string | null };

/** Captures every POST to /api/cases/** and answers with `status` and `body`; a GET (the role card) goes on. */
export async function capturePosts(page: Page, status = 200, body: unknown = {}) {
  const posts: Captured[] = [];
  await page.route("**/api/cases/**", async (route) => {
    const req = route.request();
    if (req.method() !== "POST") return route.fallback();
    posts.push({
      method: req.method(),
      path: new URL(req.url()).pathname,
      body: req.postDataJSON(),
      csrf: await req.headerValue("x-csrf-token"),
    });
    await route.fulfill({ status, json: body });
  });
  return posts;
}

/** The readable CSRF cookie a role's entry GET sets: pl_csrf (user) or pl_rep_csrf (rep). */
export async function csrfCookie(page: Page, baseURL: string | undefined, name = "pl_csrf", value = CSRF) {
  await page.context().addCookies([{ name, value, url: baseURL ?? "http://127.0.0.1:4173" }]);
}

export const shot = async (page: Page, name: string) => {
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/${name}.png`, fullPage: true });
};
