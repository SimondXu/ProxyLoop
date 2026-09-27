// Every live endpoint and name the web uses, in one module (S1-SYS-09/10 shapes,
// provisional until S1-SYS-10 lands): aligning with P-API touches only this file
// and the e2e mocks. All URLs are same-origin: the session cookie and the CSRF
// cookie come from GET /live/{case_id} on the serving origin (case_id = run_id).
// Replay GETs stay in bundleSource.ts.

export const CSRF_COOKIE = "pl_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

/** WebSocket close codes of /ws/live and /ws/rep. */
export const CLOSE = { ended: 1000, unknownRun: 4404, badStream: 1011 } as const;

/** Page modes, by URL parameter: ?live=<run_id> (the user's shell), ?rep=<case_id> (human rep). */
export type Mode = { kind: "replay" } | { kind: "live"; id: string } | { kind: "rep"; id: string };

export function pageMode(search: string): Mode {
  const q = new URLSearchParams(search);
  const rep = q.get("rep");
  const live = q.get("live");
  if (rep) return { kind: "rep", id: rep };
  if (live) return { kind: "live", id: live };
  return { kind: "replay" };
}

const enc = encodeURIComponent;
const cases = (caseId: string) => `/api/cases/${enc(caseId)}`;

export const paths = {
  session: (caseId: string) => `/live/${enc(caseId)}`,
  liveSocket: (runId: string, fromSeq: number) => `/ws/live/${enc(runId)}?from_seq=${fromSeq}`,
  // The rep's own server-filtered stream; the rep page never opens /ws/live.
  repSocket: (caseId: string, fromSeq: number) => `/ws/rep/${enc(caseId)}?from_seq=${fromSeq}`,
  approval: (caseId: string, approvalId: string) => `${cases(caseId)}/approvals/${enc(approvalId)}`,
  messages: (caseId: string) => `${cases(caseId)}/messages`,
  rep: (caseId: string) => `${cases(caseId)}/rep`,
};

export const socketUrl = (path: string, origin = location.origin) => origin.replace(/^http/, "ws") + path;

/** The contract's Decision (src/proxyloop/contract/events.py). */
export type Decision = "granted" | "denied";

/** 403 {error: "csrf" | "origin"}; 409 {error: "already_decided" | "stale"}; status 0: never sent or no response. */
export type PostResult = { ok: true } | { ok: false; status: number; error: string };

/** The approval POST body: exactly the card's terms hash and epoch. */
export const approvalBody = (card: { terms_hash: string; authority_epoch: number }, decision: Decision) => ({
  decision,
  terms_hash: card.terms_hash,
  authority_epoch: card.authority_epoch,
});

export function csrfToken(cookie: string): string | null {
  for (const part of cookie.split(";")) {
    const [name, ...value] = part.trim().split("=");
    if (name === CSRF_COOKIE) return decodeURIComponent(value.join("="));
  }
  return null;
}

/** One POST, never retried. Every failure comes back as a visible error. */
async function post(caseId: string, path: string, body: unknown): Promise<PostResult> {
  const token = csrfToken(document.cookie);
  if (token === null) {
    return { ok: false, status: 0, error: `no ${CSRF_COOKIE} cookie: open ${paths.session(caseId)} first` };
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
    text = res.ok ? "" : await res.text();
  } catch (e) {
    return { ok: false, status: 0, error: `no response: ${String(e)}` };
  }
  if (res.ok) return { ok: true };
  let error = text || res.statusText;
  try {
    const parsed = (JSON.parse(text) as { error?: unknown }).error;
    if (typeof parsed === "string") error = parsed;
  } catch {
    // not JSON: show the raw body
  }
  return { ok: false, status: res.status, error };
}

export const postApproval = (
  caseId: string,
  card: { approval_id: string; terms_hash: string; authority_epoch: number },
  decision: Decision,
) => post(caseId, paths.approval(caseId, card.approval_id), approvalBody(card, decision));

/** User chat → a user.msg ingress. */
export const postMessage = (caseId: string, text: string) => post(caseId, paths.messages(caseId), { text });

/** Rep utterance → a partner utt.final on the cp lane. */
export const postRep = (caseId: string, text: string) => post(caseId, paths.rep(caseId), { text });
