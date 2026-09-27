import { expect, test, type Page, type Response } from "@playwright/test";

// The web against the real API (S1-SYS-18): nothing in the browser is mocked.
// Each test owns one stub case of tests/web/wiring_server.py (its mode is fixed
// there); texts and ids are read from the case's own log through the real API.
type Ev = { seq: number; event_id: string; type: string; actor: string; cause_ids: string[]; payload: Record<string, unknown> };
type Sock = { path: string; frames: string[] };

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

  await page.goto("/");
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
  await expect(page.getByRole("region", { name: "User chat" })).toContainText(said);
  await expect(page.getByRole("region", { name: "Rep" })).toContainText(String(one(seed, "utt.delivered").payload.text_heard));

  const status = card.getByLabel("Approval status");
  const got = await click(page, id, "approvals/", () => card.getByRole("button", { name: "Approve" }).click());
  expect(got).toEqual({ status: 200, body: { status: "posted" } });
  await expect(status).toHaveText("sent: waiting for the kernel's decision");
  await expect(status).toHaveText("decided: granted by ui");

  // The same post again, with the same token: single use.
  const requested = one(seed, "approval.requested").payload;
  const body = { decision: "granted", terms_hash: requested.terms_hash, authority_epoch: requested.authority_epoch };
  const path = `/api/cases/${id}/approvals/${String(requested.approval_id)}`;
  expect(await postFrom(page, path, body, await cookie(page, "pl_csrf"))).toEqual({ status: 409, body: { error: "already_decided" } });
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
  expect(got).toEqual({ status: 409, body: { error: "stale", reason: "stale_epoch" } });
  await expect(card.getByRole("alert")).toHaveText("409 stale: stale_epoch");
  await expect(card.getByLabel("Approval status")).toHaveText("stale: the authority epoch moved past this card");
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
  await expect(status).toHaveText("refused: stale_epoch");
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
  const after = await log(page, id);
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
  const id = "wire-chat";
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

test("g) chat: a message is 200 sent, and shows in the User chat lane when its user.msg arrives", async ({ page }) => {
  const id = "wire-chat";
  await openLive(page, id);
  const text = "Stop, do not accept anything yet.";
  await page.getByRole("textbox", { name: "Message to the agent" }).fill(text);
  const got = await click(page, id, "messages", () => page.getByRole("button", { name: "Send" }).click());
  expect(got).toEqual({ status: 200, body: { status: "sent" } });
  await expect(page.getByRole("region", { name: "User chat" }).getByText(text, { exact: true })).toBeVisible();
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
  const after = await log(page, id);
  expect([count(after, "user.msg"), count(after, "utt.final"), count(after, "approval.post")]).toEqual([1, 1, 0]);
});
