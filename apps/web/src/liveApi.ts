// Every live endpoint and name the web uses, in one module (S1-SYS-09/10 shapes):
// aligning with P-API touches only this file and the e2e mocks. All URLs are
// same-origin (case_id = run_id). Each role enters through its own GET, which sets
// an HttpOnly session cookie and a readable CSRF cookie, then 303s to the page:
//   GET /live/{case_id}: pl_session + pl_csrf         → /?live={case_id}
//   GET /rep/{case_id}:  pl_rep_session + pl_rep_csrf → /?rep={case_id}
//   GET /start:          pl_op_session + pl_op_csrf   → /?start (the operator, S1-SYS-33)
// Replay GETs stay in bundleSource.ts.

/** The user's shell ("live"), the human rep ("rep") or the operator's start page ("start"). */
export type Role = "live" | "rep" | "start";
export const CSRF_COOKIE: Record<Role, string> = { live: "pl_csrf", rep: "pl_rep_csrf", start: "pl_op_csrf" };
export const CSRF_HEADER = "X-CSRF-Token";

/**
 * WebSocket close codes of /ws/live and /ws/rep. 4403: missing or foreign-role cookie,
 * or foreign Origin. 1006 before open: the upgrade was refused (Origin) or the API is unreachable.
 */
export const CLOSE = { ended: 1000, abnormal: 1006, forbidden: 4403, unknownRun: 4404, badStream: 1011 } as const;

/** Page modes, by URL parameter: ?live=<run_id> (the user's shell), ?rep=<case_id> (human rep), ?start. */
export type Mode = { kind: "replay" } | { kind: "start" } | { kind: "live"; id: string } | { kind: "rep"; id: string };

export function pageMode(search: string): Mode {
  const q = new URLSearchParams(search);
  const rep = q.get("rep");
  const live = q.get("live");
  if (rep) return { kind: "rep", id: rep };
  if (live) return { kind: "live", id: live };
  if (q.has("start")) return { kind: "start" };
  return { kind: "replay" };
}

const enc = encodeURIComponent;
const cases = (caseId: string) => `/api/cases/${enc(caseId)}`;

export const paths = {
  start: "/start",
  models: "/api/models",
  cases: "/api/cases",
  liveSession: (caseId: string) => `/live/${enc(caseId)}`,
  repSession: (caseId: string) => `/rep/${enc(caseId)}`,
  liveSocket: (runId: string, fromSeq: number) => `/ws/live/${enc(runId)}?from_seq=${fromSeq}`,
  // The rep's own server-filtered stream of rebuilt frames, numbered 0, 1, 2, … on
  // that stream (from_seq is a rep seq); the rep page never opens /ws/live.
  repSocket: (caseId: string, fromSeq: number) => `/ws/rep/${enc(caseId)}?from_seq=${fromSeq}`,
  approval: (caseId: string, approvalId: string) => `${cases(caseId)}/approvals/${enc(approvalId)}`,
  messages: (caseId: string) => `${cases(caseId)}/messages`,
  rep: (caseId: string) => `${cases(caseId)}/rep`,
};

/** Where a role gets its cookies. */
export const entry = (role: Role, caseId: string) =>
  role === "start" ? paths.start : (role === "live" ? paths.liveSession : paths.repSession)(caseId);

export const socketUrl = (path: string, origin = location.origin) => origin.replace(/^http/, "ws") + path;

/** The contract's Decision (src/proxyloop/contract/events.py). */
export type Decision = "granted" | "denied";

/** 403 {error: "csrf" | "origin"}; 409 {error: "already_decided" | "stale", reason?}; status 0: never sent or no response. */
export type Failed = { ok: false; status: number; error: string; reason?: string };
export type PostResult = { ok: true; body?: unknown } | Failed;

/** The approval POST body: exactly the card's terms hash and epoch. */
export const approvalBody = (card: { terms_hash: string; authority_epoch: number }, decision: Decision) => ({
  decision,
  terms_hash: card.terms_hash,
  authority_epoch: card.authority_epoch,
});

export function csrfToken(cookie: string, role: Role): string | null {
  for (const part of cookie.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === CSRF_COOKIE[role]) return decodeURIComponent(value.join("="));
  }
  return null;
}

const json = (text: string): unknown => {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
};

/** One POST, never retried. Every failure comes back as a visible error. */
async function post(role: Role, caseId: string, path: string, body: unknown): Promise<PostResult> {
  let token: string | null;
  try {
    token = csrfToken(document.cookie, role);
  } catch {
    return { ok: false, status: 0, error: `bad ${CSRF_COOKIE[role]} cookie` }; // decodeURIComponent: URIError
  }
  if (token === null) {
    return { ok: false, status: 0, error: `no ${CSRF_COOKIE[role]} cookie: open ${entry(role, caseId)} first` };
  }
  let res: Response;
  let text: string;
  try {
    res = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", [CSRF_HEADER]: token },
      body: JSON.stringify(body),
    });
    text = await res.text();
  } catch (e) {
    return { ok: false, status: 0, error: `no response: ${String(e)}` };
  }
  if (res.ok) return { ok: true, body: json(text) };
  let error = text || res.statusText;
  let reason: string | undefined; // a 409 stale says why (guard.decide's reason)
  try {
    const parsed = JSON.parse(text) as { error?: unknown; reason?: unknown };
    if (typeof parsed.error === "string") error = parsed.error;
    if (typeof parsed.reason === "string") reason = parsed.reason;
  } catch {
    // not JSON: show the raw body
  }
  return { ok: false, status: res.status, error, reason };
}

export const postApproval = (
  caseId: string,
  card: { approval_id: string; terms_hash: string; authority_epoch: number },
  decision: Decision,
) => post("live", caseId, paths.approval(caseId, card.approval_id), approvalBody(card, decision));

/** User chat → a user.msg ingress. */
export const postMessage = (caseId: string, text: string) => post("live", caseId, paths.messages(caseId), { text });

/** Rep utterance → a partner utt.final on the cp lane. */
export const postRep = (caseId: string, text: string) => post("rep", caseId, paths.rep(caseId), { text });

/** GET /api/models (S1-SYS-33): the options serve offers, as sent; 500 {error: "options", reason} is an error. */
export async function getOptions(): Promise<{ ok: true; body: unknown } | { ok: false; error: string }> {
  let res: Response;
  let text: string;
  try {
    res = await fetch(paths.models, { credentials: "same-origin" });
    text = await res.text();
  } catch (e) {
    return { ok: false, error: `no response: ${String(e)}` };
  }
  if (res.ok) return { ok: true, body: json(text) };
  const body = json(text) as { error?: unknown; reason?: unknown } | undefined;
  const why = typeof body?.reason === "string" ? `: ${body.reason}` : "";
  return { ok: false, error: `${res.status} ${typeof body?.error === "string" ? body.error : text || res.statusText}${why}` };
}

export type StartRequest = { task_ref: string; models: Record<string, string>; rep: "sim" | "human" };

/** POST /api/cases with the operator's token: 201 {case_id}, else the refusal as sent. Never retried. */
export async function startCase(body: StartRequest): Promise<{ ok: true; caseId: string } | Failed> {
  const r = await post("start", "", paths.cases, body);
  if (!r.ok) return r;
  const id = (r.body as { case_id?: unknown } | undefined)?.case_id;
  return typeof id === "string" && id !== "" ? { ok: true, caseId: id } : { ok: false, status: 0, error: "no case_id in the answer" };
}
