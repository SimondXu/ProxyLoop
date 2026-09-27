import { expect, test, type Page, type Response } from "@playwright/test";

// The web against the real API (S1-SYS-18): nothing in the browser is mocked.
// Each test owns one stub case of tests/web/wiring_server.py (its mode is fixed
// there); texts and ids are read from the case's own log through the real API.
type Ev = { seq: number; event_id: string; type: string; actor: string; cause_ids: string[]; payload: Record<string, unknown> };
type Sock = { path: string; frames: string[] };
// The stub kernel decides DECIDE_AFTER_S = 2 s after a post (tests/support/web_wiring.py): wait well past it.
const DECIDED_MS = 10_000;

/** A run's events.jsonl, through the real replay endpoint. */
async function log(page: Page, id: string): Promise<Ev[]> {
  const res = await page.request.get(`/api/replay/${id}/events`);
  expect(res.status()).toBe(200);
  return (await res.text())
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Ev);
}
const one = (events: Ev[], type: string) => {
  const found = events.filter((e) => e.type === type);
  expect(found, type).toHaveLength(1);
  return found[0] as Ev;
};
const count = (events: Ev[], type: string) => events.filter((e) => e.type === type).length;

/** Every WebSocket the page opens, with the frames it receives. */
function sockets(page: Page): Sock[] {
  const seen: Sock[] = [];
  page.on("websocket", (ws) => {
    const url = new URL(ws.url());
    const sock: Sock = { path: url.pathname + url.search, frames: [] };
    seen.push(sock);
    ws.on("framereceived", (f) => sock.frames.push(String(f.payload)));
  });
  return seen;
}
const seqs = (s: Sock | undefined) => (s?.frames ?? []).map((f) => (JSON.parse(f) as { seq: number }).seq);
const range = (n: number) => [...Array(n).keys()];

/** The role's entry GET, not followed: its status, Location and cookie names. */
async function entry(page: Page, path: string) {
  const res = await page.request.get(path, { maxRedirects: 0 });
  const cookies = res
    .headersArray()
    .filter((h) => h.name.toLowerCase() === "set-cookie")
    .map((h) => h.value.split("=")[0])
    .sort();
  return { status: res.status(), location: res.headers()["location"], cookies };
}

const cookie = async (page: Page, name: string) => (await page.context().cookies()).find((c) => c.name === name)?.value;

/** A POST from the page (same origin, its cookies); `token` null sends no X-CSRF-Token. */
function postFrom(page: Page, path: string, body: unknown, token: string | null | undefined) {
  return page.evaluate(
    async ({ path, body, token }) => {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["X-CSRF-Token"] = token;
      const res = await fetch(path, { method: "POST", headers, body: JSON.stringify(body) });
      return { status: res.status, body: (await res.json()) as unknown };
    },
    { path, body, token: token ?? null },
  );
}

/**
 * A 409 as serve.cases answers it: {error, reason?}. `error` is pinned; `reason`, when
 * present, is a non-empty string from an open set (guard.decide's), so its value is not.
 */
function conflict(got: { status: number; body: unknown }, error: "already_decided" | "stale"): string | undefined {
  expect(got.status).toBe(409);
  const body = got.body as Record<string, unknown>;
  expect(Object.keys(body).filter((k) => k !== "reason")).toEqual(["error"]);
  expect(body.error).toBe(error);
  if (!("reason" in body)) return undefined;
  expect(typeof body.reason === "string" && body.reason !== "", "reason is a non-empty string").toBe(true);
  return String(body.reason);
}

/** The authority strip sits behind a disclosure in the sticky header: open it (idempotent). */
async function authority(page: Page) {
  await page.locator("details.authority").evaluate((d: HTMLDetailsElement) => (d.open = true));
  return page.getByRole("region", { name: "Authority" });
}

async function openLive(page: Page, id: string) {
  await page.goto(`/live/${id}`);
  await expect(page).toHaveURL(`/?live=${id}`);
  const card = page.getByRole("article", { name: /^Approval / });
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  return card;
}

const isPost = (id: string, what: string) => (r: Response) =>
  r.request().method() === "POST" && new URL(r.url()).pathname.startsWith(`/api/cases/${id}/${what}`);

async function click(page: Page, id: string, what: string, act: () => Promise<void>) {
  const [res] = await Promise.all([page.waitForResponse(isPost(id, what)), act()]);
  return { status: res.status(), body: (await res.json()) as unknown };
}

test("a) replay: lists evidence/s0, loads a run with a real_http Fast sentence and a prompt; unknown runs are 404s and a visible error", async ({
  page,
}) => {
  const listed = (await (await page.request.get("/api/bundles")).json()) as { bundles: { run_id: string; root: string }[] };
  const s0 = listed.bundles.filter((b) => b.root === "s0").map((b) => b.run_id);
  expect(s0.length).toBeGreaterThan(0);
  const spoken: string[] = [];
  for (const id of s0) if ((await log(page, id)).some((e) => e.type === "fast.sentence")) spoken.push(id);
  const run = spoken[0] ?? "";
  expect(run, "an evidence/s0 run with a fast.sentence").not.toBe("");

  await page.goto("/?view=engineer"); // the lanes and the prompt drawer: the engineer view
  const select = page.getByRole("combobox", { name: "Run" });
  await expect(select.locator("option")).toHaveCount(listed.bundles.length);
  await select.selectOption(run);
  await expect(page.getByRole("region", { name: "Run" })).toContainText(run);
  const timeline = page.getByRole("slider", { name: "Timeline" });
  await timeline.fill((await timeline.getAttribute("max")) ?? "0");
  const fast = page
    .getByRole("region", { name: /^Fast-[UC]$/ })
    .getByRole("article", { name: /^fast\.sentence #/ })
    .filter({ has: page.getByText(/^model: (?!unknown ).+ · real_http$/) });
  await expect(fast.first()).toBeVisible();
  await page.getByRole("article", { name: /^llm\.call #/ }).first().getByRole("button", { name: "prompt" }).click();
  const drawer = page.getByRole("dialog", { name: "Prompt drill-down" });
  await expect(drawer.getByText(/verbatim from prompts\.jsonl/)).toBeVisible();
  await expect(drawer.getByLabel("Prompt content")).not.toBeEmpty();

  expect((await page.request.get("/api/replay/no-such-run/events")).status()).toBe(404);
  expect((await entry(page, "/live/no-such-run")).status).toBe(404);
  await page.goto("/?live=no-such-run");
  await expect(page.getByRole("alert")).toHaveText("Stream stopped: unknown run (4404 unknown run)");
  await expect(page.getByRole("heading", { name: "ProxyLoop live · no-such-run" })).toBeVisible();
});

test("b) live: /live sets the cookies and 303s, /ws/live streams the seed, Approve posts once and the kernel decides", async ({
  page,
}) => {
  const id = "wire-approve";
  expect(await entry(page, `/live/${id}`)).toEqual({ status: 303, location: `/?live=${id}`, cookies: ["pl_csrf", "pl_session"] });
  const seen = sockets(page);
  const card = await openLive(page, id);
  const seed = await log(page, id);
  expect(seen.map((s) => s.path)).toEqual([`/ws/live/${id}?from_seq=0`]);
  await expect.poll(() => seqs(seen[0])).toEqual(range(seed.length));
  const said = String(one(seed, "user.msg").payload.text);
  await expect(page.getByRole("list", { name: "Chat transcript" })).toContainText(`You: ${said}`);
  await expect(page.getByRole("list", { name: "Call transcript" })).toContainText(`Agent: ${String(one(seed, "utt.delivered").payload.text_heard)}`);

  const status = card.getByLabel("Approval status");
  const got = await click(page, id, "approvals/", () => card.getByRole("button", { name: "Approve" }).click());
  expect(got).toEqual({ status: 200, body: { status: "posted" } });
  await expect(status).toHaveText("sent: waiting for the kernel's decision");
  await expect(status).toHaveText("decided: granted by ui", { timeout: DECIDED_MS });

  // The same post again, with the same token: single use.
  const requested = one(seed, "approval.requested").payload;
  const body = { decision: "granted", terms_hash: requested.terms_hash, authority_epoch: requested.authority_epoch };
  const path = `/api/cases/${id}/approvals/${String(requested.approval_id)}`;
  conflict(await postFrom(page, path, body, await cookie(page, "pl_csrf")), "already_decided");
  await expect(status).toHaveText("decided: granted by ui");
  await expect(card.getByRole("alert")).toHaveCount(0);
  const after = await log(page, id);
  expect([count(after, "approval.post"), count(after, "approval.decided")]).toEqual([1, 1]);
  expect(one(after, "approval.decided").cause_ids).toEqual([one(after, "approval.post").event_id]);
});

test("c) stale: an epoch bumped in the board before the post is a 409 stale, shown on the card, and nothing is posted", async ({
  page,
}) => {
  const id = "wire-stale";
  const card = await openLive(page, id);
  const got = await click(page, id, "approvals/", () => card.getByRole("button", { name: "Approve" }).click());
  const reason = conflict(got, "stale");
  expect(reason, "a stale refusal from guard.decide says why").toBeDefined();
  await expect(card.getByRole("alert")).toHaveText(`409 stale: ${String(reason)}`);
  // #150 nit 4: the status line names the 409's own reason (here the epoch did move: stale_epoch).
  await expect(card.getByLabel("Approval status")).toHaveText(`stale: ${String(reason)}`);
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
  const after = await log(page, id);
  expect([count(after, "authority.epoch"), count(after, "approval.post"), count(after, "action.denied")]).toEqual([1, 0, 0]);
});

test("d) refused: a 200, then the kernel's action.denied citing the card, shown as refused with its reason", async ({ page }) => {
  const id = "wire-refuse";
  const card = await openLive(page, id);
  const status = card.getByLabel("Approval status");
  const got = await click(page, id, "approvals/", () => card.getByRole("button", { name: "Approve" }).click());
  expect(got).toEqual({ status: 200, body: { status: "posted" } });
  await expect(status).toHaveText("sent: waiting for the kernel's decision");
  await expect(status).toHaveText(/^refused: ./, { timeout: DECIDED_MS });
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
  const after = await log(page, id);
  await expect(status).toHaveText(`refused: ${String(one(after, "action.denied").payload.reason)}`);
  expect(one(after, "action.denied").cause_ids).toEqual([one(after, "approval.requested").event_id]);
  expect(count(after, "approval.post")).toBe(0);
});

test("e) unavailable: the handover raises, the card shows the 503, and nothing retries", async ({ page }) => {
  const id = "wire-raise";
  const posts: string[] = [];
  page.on("request", (r) => r.method() === "POST" && posts.push(new URL(r.url()).pathname));
  const card = await openLive(page, id);
  const got = await click(page, id, "approvals/", () => card.getByRole("button", { name: "Approve" }).click());
  expect(got).toEqual({ status: 503, body: { error: "unavailable" } });
  await expect(card.getByRole("alert")).toHaveText("503 unavailable");
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  await page.waitForTimeout(1_500);
  expect(posts).toHaveLength(1);
  expect(count(await log(page, id), "approval.post")).toBe(0);
});

test("f, i) a missing or wrong X-CSRF-Token is 403 csrf; a foreign Origin is 403 origin; nothing reaches the case", async ({ page }) => {
  const id = "wire-csrf";
  const card = await openLive(page, id);
  await expect(card).toBeVisible();
  const seed = await log(page, id);
  const token = await cookie(page, "pl_csrf");
  expect(token).toBeTruthy();
  const messages = `/api/cases/${id}/messages`;
  const requested = one(seed, "approval.requested").payload;
  const approval = `/api/cases/${id}/approvals/${String(requested.approval_id)}`;
  const body = { decision: "granted", terms_hash: requested.terms_hash, authority_epoch: requested.authority_epoch };
  const csrf = { status: 403, body: { error: "csrf" } };
  expect(await postFrom(page, messages, { text: "no token" }, null)).toEqual(csrf);
  expect(await postFrom(page, messages, { text: "wrong token" }, "0".repeat(64))).toEqual(csrf);
  expect(await postFrom(page, approval, body, null)).toEqual(csrf);
  expect(await postFrom(page, approval, body, "0".repeat(64))).toEqual(csrf);
  // A browser never lets a page set Origin; Playwright's request context can.
  const foreign = await page.request.post(messages, {
    data: { text: "from elsewhere" },
    headers: { Origin: "http://evil.example", "X-CSRF-Token": token ?? "" },
  });
  expect([foreign.status(), await foreign.json()]).toEqual([403, { error: "origin" }]);
  const after = await log(page, id);
  expect(after).toHaveLength(seed.length);
});

test("g) chat: a message is 200 sent, and shows in the chat pane when its user.msg arrives", async ({ page }) => {
  const id = "wire-chat";
  await openLive(page, id);
  const text = "Stop, do not accept anything yet.";
  await page.getByRole("textbox", { name: "Message to the assistant" }).fill(text);
  const got = await click(page, id, "messages", () => page.getByRole("button", { name: "Send" }).click());
  expect(got).toEqual({ status: 200, body: { status: "sent" } });
  await expect(page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem").last()).toHaveText(`You: ${text}`);
  await expect(page.getByRole("list", { name: "Pending" })).toHaveCount(0);
  const msgs = (await log(page, id)).filter((e) => e.type === "user.msg").map((e) => e.payload.text);
  expect(msgs.at(-1)).toBe(text);
});

test("h) rep: /rep 303s to ?rep, opens /ws/rep only, sees only public cp speech, speaks, and cannot use the user's routes", async ({
  page,
}) => {
  const id = "wire-rep";
  expect(await entry(page, `/rep/${id}`)).toEqual({ status: 303, location: `/?rep=${id}`, cookies: ["pl_rep_csrf", "pl_rep_session"] });
  const seen = sockets(page);
  // Every HTTP request the rep's page makes (the checks' own page.request calls are not the page's).
  const http: string[] = [];
  page.on("request", (r) => http.push(new URL(r.url()).pathname));
  const api = () => http.filter((p) => p.startsWith("/api/") || p.startsWith("/ws/"));
  await page.goto(`/rep/${id}`);
  await expect(page).toHaveURL(`/?rep=${id}`);
  const seed = await log(page, id);
  const heard = String(one(seed, "utt.delivered").payload.text_heard);
  const hidden = [String(one(seed, "summary.updated").payload.text), String(one(seed, "user.msg").payload.text)];
  const transcript = page.getByRole("list", { name: "Call transcript" });
  await expect(transcript.getByRole("listitem")).toHaveText(["Call: call connected", `Agent: ${heard}`]);
  expect(seen.map((s) => s.path)).toEqual([`/ws/rep/${id}?from_seq=0`]);
  await expect.poll(() => seqs(seen[0])).toEqual([0, 1]);
  for (const text of hidden) {
    await expect(page.locator("body")).not.toContainText(text);
    expect(seen[0]?.frames.join("\n")).not.toContain(text);
  }

  const line = "We can do 65 dollars a month on a 24-month term.";
  await page.getByRole("textbox", { name: "Say to the agent" }).fill(line);
  const got = await click(page, id, "rep", () => page.getByRole("button", { name: "Send" }).click());
  expect(got).toEqual({ status: 200, body: { status: "sent" } });
  await expect(transcript.getByRole("listitem").last()).toHaveText(`You: ${line}`);
  await expect.poll(() => seqs(seen[0])).toEqual([0, 1, 2]);
  expect(api()).toEqual([`/api/cases/${id}/rep`]); // the page itself reads no replay, listing or /ws/live

  // Cross-role: with both roles' cookies in this browser, neither token opens the other's routes.
  expect((await entry(page, `/live/${id}`)).status).toBe(303);
  const rep = await cookie(page, "pl_rep_csrf");
  const user = await cookie(page, "pl_csrf");
  const requested = one(seed, "approval.requested").payload;
  const body = { decision: "granted", terms_hash: requested.terms_hash, authority_epoch: requested.authority_epoch };
  const csrf = { status: 403, body: { error: "csrf" } };
  expect(await postFrom(page, `/api/cases/${id}/messages`, { text: "as the user" }, rep)).toEqual(csrf);
  expect(await postFrom(page, `/api/cases/${id}/approvals/${String(requested.approval_id)}`, body, rep)).toEqual(csrf);
  expect(await postFrom(page, `/api/cases/${id}/rep`, { text: "with the user's token" }, user)).toEqual(csrf);
  expect(seen.map((s) => s.path)).toEqual([`/ws/rep/${id}?from_seq=0`]);
  expect(api().filter((p) => ["/api/replay/", "/api/bundles", "/ws/live"].some((f) => p.startsWith(f)))).toEqual([]);
  const after = await log(page, id);
  expect([count(after, "user.msg"), count(after, "utt.final"), count(after, "approval.post")]).toEqual([1, 1, 0]);
});

// S1-SYS-31: the start page over the real start routes and tests/support/web_wiring.py's
// WiringStarter, whose task picks the outcome.
type Option = { id: string; lane: string; label: string; endpoint: string; model_id: string; default: boolean };
const LANES = [
  ["fast_user", "Chat voice (Fast-U)"],
  ["fast_cp", "Phone voice (Fast-C)"],
  ["slow", "Planner (Slow)"],
] as const;
const REP = { sim: "Simulated rep", human: "A person" } as const;
const shot = async (page: Page, name: string) => {
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/${name}.png`, fullPage: true });
};

async function openStart(page: Page) {
  await page.goto("/start");
  await expect(page).toHaveURL("/?start");
  await expect(page.getByRole("button", { name: "Start" })).toBeEnabled();
}

async function start(page: Page, task: string, rep: "sim" | "human" = "sim") {
  await openStart(page);
  await page.getByRole("radiogroup", { name: "Task" }).getByRole("radio").and(page.locator(`[value="${task}"]`)).check();
  await page.getByRole("radio", { name: REP[rep] }).check();
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/cases"),
    page.getByRole("button", { name: "Start" }).click(),
  ]);
  return { status: res.status(), body: (await res.json()) as Record<string, unknown> };
}

test("j) start: /start sets the operator's cookies and 303s; each lane lists only its own options, its default preselected", async ({
  page,
}) => {
  expect(await entry(page, "/start")).toEqual({ status: 303, location: "/?start", cookies: ["pl_op_csrf", "pl_op_session"] });
  const offered = (await (await page.request.get("/api/models")).json()) as { options: Option[]; tasks: string[] };
  await openStart(page);
  await expect(page.getByRole("note")).toHaveCount(0); // the cookie is there: no "open /start" link
  await expect(page.getByRole("radiogroup", { name: "Task" }).locator("code")).toHaveText(offered.tasks);
  await expect(page.getByRole("radio", { name: "sim" })).toBeChecked();
  await page.getByText("Advanced: models").click();
  for (const [lane, title] of LANES) {
    const own = offered.options.filter((o) => o.lane === lane);
    const select = page.getByRole("combobox", { name: title });
    await expect(select.locator("option")).toHaveText(own.map((o) => `${o.label} · ${o.model_id} · ${o.endpoint}`));
    await expect(select).toHaveValue(own.find((o) => o.default)?.id ?? "no default");
  }
  await shot(page, "start-page");
});

test("k) start: Start → 201 → /live/{case} → /?live=, and the socket streams the new case", async ({ page }) => {
  const seen = sockets(page);
  await openStart(page);
  const created = page.waitForResponse((r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/cases");
  await page.getByRole("button", { name: "Start" }).click();
  expect((await created).status()).toBe(201); // its body is gone with the navigation: the id comes from the URL
  await expect(page).toHaveURL(/\/\?live=started-\d+$/);
  const id = new URL(page.url()).searchParams.get("live") ?? "";
  await expect(page.getByRole("article", { name: /^Approval / }).getByLabel("Approval status")).toHaveText("awaiting your decision");
  const n = (await log(page, id)).length;
  await expect.poll(() => seqs(seen.find((s) => s.path.startsWith(`/ws/live/${id}`)))).toEqual(range(n));
});

test("l) start: busy 409, unknown_model 400 and a dead kernel's 503 are shown, and nothing retries", async ({ page }) => {
  const posts: string[] = [];
  page.on("request", (r) => r.method() === "POST" && posts.push(new URL(r.url()).pathname));
  const alert = page.getByRole("alert");
  expect(await start(page, "wire-busy")).toEqual({ status: 409, body: { error: "start", reason: "busy" } });
  await expect(alert).toHaveText("Not started: 409 start: busy (a session is already running: wait for it to end)");
  expect(await start(page, "wire-unknown-model")).toEqual({ status: 400, body: { error: "start", reason: "unknown_model" } });
  await expect(alert).toHaveText("Not started: 400 start: unknown_model (the kernel does not know a chosen model)");
  expect(await start(page, "wire-dead-kernel")).toEqual({ status: 503, body: { error: "unavailable" } });
  await expect(alert).toHaveText(/^Not started: 503 unavailable \(/);
  await page.waitForTimeout(500);
  expect(posts).toEqual(["/api/cases", "/api/cases", "/api/cases"]);
  await expect(page).toHaveURL("/?start");
});

test("m) start: a missing or wrong X-CSRF-Token, or the user's token, is 403 csrf and starts nothing", async ({ page }) => {
  await page.goto("/live/wire-csrf"); // the user's pair, which is not the operator's
  await openStart(page);
  const body = { task_ref: "wire-start", models: {} };
  const csrf = { status: 403, body: { error: "csrf" } };
  const before = (await (await page.request.get("/api/bundles")).json()) as { bundles: unknown[] };
  expect(await postFrom(page, "/api/cases", body, null)).toEqual(csrf);
  expect(await postFrom(page, "/api/cases", body, "0".repeat(64))).toEqual(csrf);
  expect(await postFrom(page, "/api/cases", body, await cookie(page, "pl_csrf"))).toEqual(csrf);
  const after = (await (await page.request.get("/api/bundles")).json()) as { bundles: unknown[] };
  expect(after.bundles).toHaveLength(before.bundles.length);
});

test("n) start: rep human shows the /rep link for a new tab, and the live link", async ({ page }) => {
  const got = await start(page, "wire-start-human", "human");
  expect(got.status).toBe(201);
  const id = String(got.body.case_id);
  const started = page.getByLabel("Started");
  await expect(started.getByRole("link", { name: "Open the rep page" })).toHaveAttribute("href", `/rep/${id}`);
  await expect(started.getByRole("link", { name: "Open the rep page" })).toHaveAttribute("target", "_blank");
  await expect(page.getByRole("button", { name: "Start" })).toBeDisabled();
  const [rep] = await Promise.all([page.context().waitForEvent("page"), started.getByRole("link", { name: "Open the rep page" }).click()]);
  await expect(rep).toHaveURL(`/?rep=${id}`);
  await expect(rep.getByRole("list", { name: "Call transcript" }).getByRole("listitem").first()).toHaveText("Call: call connected");
  await shot(rep, "rep-page-wiring");
  await started.getByRole("link", { name: "open the live page" }).click();
  await expect(page).toHaveURL(`/?live=${id}`);
});

test("o) live: the authority strip and the card's read-back progress, from the stub's real-Bus events", async ({ page }) => {
  const id = "wire-authority";
  const card = await openLive(page, id);
  const events = await log(page, id);
  const strip = await authority(page);
  const status = events.filter((e) => e.type === "status.changed").at(-1)?.payload.status;
  await expect(strip.getByLabel("Case status")).toHaveText(`status ${String(status)}`);
  const fence = one(events, "authority.fence").payload;
  expect(fence.op).toBe("raised");
  await expect(strip.getByLabel("Fence")).toHaveText(`fence raised (${String(fence.fence_id)})`);
  await expect(strip.getByLabel("Epoch")).toHaveText("epoch 0");
  const revoked = one(events, "speak.revoked");
  await expect(strip.getByLabel("Last revoked")).toHaveText(`last speak.revoked ${String(revoked.payload.reason)} (${revoked.actor})`);
  const denied = one(events, "action.denied");
  await expect(strip.getByLabel("Last denied")).toHaveText(
    `last action.denied ${String(denied.payload.intent)}: ${String(denied.payload.reason)} (${denied.actor})`,
  );
  // #173 N-3: the read-back in the kernel's order. The offer as first stated (r1) was only
  // partly heard before the card; the card's revision was confirmed, and nothing regresses after it.
  const requested = one(events, "approval.requested");
  const readbacks = events.filter((e) => e.type === "readback.updated");
  const statuses = (e: Ev | undefined) => Object.entries((e?.payload.slot_statuses ?? {}) as Record<string, string>);
  const partial = readbacks.filter((e) => e.seq < requested.seq && e.payload.revision !== requested.payload.revision);
  expect(partial.flatMap((e) => statuses(e).map(([, s]) => s))).toContain("heard");
  const own = readbacks.filter((e) => e.payload.revision === requested.payload.revision);
  for (const e of readbacks.filter((e) => e.seq > requested.seq)) expect(statuses(e).every(([, s]) => s === "confirmed")).toBe(true);
  await expect(card.getByRole("list", { name: "Read-back progress" }).getByRole("listitem")).toHaveText(
    statuses(own.at(-1)).map(([field, s]) => `${field}: ${s}`),
  );
  expect(statuses(own.at(-1)).map(([, s]) => s)).toEqual(Array(5).fill("confirmed"));
  await expect(card.getByLabel("Fence note")).toHaveText("fence raised: the accept waits until it clears");
  await shot(page, "live-strip");
});
