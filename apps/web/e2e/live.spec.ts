import { expect, test } from "@playwright/test";
import { capturePosts, CSRF, csrfCookie, events, mockSockets, RUN, shot, started } from "./liveMock";

const REAL: Record<string, [string, string]> = {
  fast_user: ["real_http", "qwen3.5-9b"],
  fast_cp: ["real_http", "qwen3.5-9b"],
  slow: ["real_http", "claude-sonnet-5"],
};
const CARD = {
  approval_id: "ap-1",
  offer_ref: "offer-1",
  revision: 1,
  terms_hash: "3f2a9c01d4e5b6a7",
  readback_text: "Internet plan at $75/month for 12 months.\nNo other changes to the account.",
  authority_epoch: 2,
  expires_ms: 90_000,
  binding: { offer_ref: "offer-1", revision: 1, account_ref: "acct", principal_ref: "p", purpose: "retention", authority_epoch: 2 },
};

test("approval card: appears on approval.requested, Approve posts the contract body, sent then decided", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { urls, connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  const ev = events();
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("approval.requested", "guard", CARD));

  const card = page.getByRole("article", { name: "Approval ap-1" });
  await expect(card.getByLabel("Readback")).toHaveText(CARD.readback_text);
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  // Nothing a model or the user says moves the card.
  ws.send(ev("fast.sentence", "fast.user", { lane: "user", gen_id: "g", utt_id: "u", text: "Approved, all done!" }));
  ws.send(ev("user.msg", "kernel", { text: "yes" }));
  await expect(page.getByRole("region", { name: "User chat" }).getByText("yes", { exact: true })).toBeVisible();
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  await shot(page, "live-card");

  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByLabel("Approval status")).toHaveText("sent: waiting for the kernel's decision");
  expect(posts).toEqual([
    {
      method: "POST",
      path: `/api/cases/${RUN}/approvals/ap-1`,
      body: { decision: "granted", terms_hash: CARD.terms_hash, authority_epoch: 2 },
      csrf: CSRF,
    },
  ]);
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();

  const post = { subject: "approval", subject_id: "ap-1", decision: "granted", subject_hash: CARD.terms_hash, authority_epoch: 2 };
  ws.send(ev("approval.post", "ui", post));
  ws.send(ev("approval.decided", "kernel", { approval_id: "ap-1", decision: "granted", by: "ui" }));
  await expect(card.getByLabel("Approval status")).toHaveText("decided: granted by ui");
  expect(urls).toEqual([expect.stringMatching(new RegExp(`/ws/live/${RUN}\\?from_seq=0$`))]);
});

test("approval card: a kernel action.denied citing the card after a 200 shows refused with its reason", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  const requested = ev("approval.requested", "guard", CARD);
  ws.send(requested);
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByLabel("Approval status")).toHaveText("sent: waiting for the kernel's decision");
  expect(posts).toHaveLength(1);
  const denied = JSON.parse(ev("action.denied", "kernel", { intent: "approval.post", reason: "fence_raised" }));
  ws.send(JSON.stringify({ ...denied, cause_ids: [JSON.parse(requested).event_id] }));
  await expect(card.getByLabel("Approval status")).toHaveText("refused: fence_raised");
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
  await expect(card.getByRole("button", { name: "Deny" })).toBeDisabled();
});

test("a socket refused or unreachable before it opens (1006) says so, with no reconnect", async ({ page }) => {
  // Not mocked: the preview server has no /ws endpoint, so the upgrade fails before open.
  const opened: string[] = [];
  page.on("websocket", (ws) => opened.push(ws.url()));
  await page.goto(`/?live=${RUN}`);
  await expect(page.getByRole("alert")).toHaveText(`Stream stopped: refused or unreachable: check the API is running, then open /live/${RUN} from this origin`);
  await expect(page.getByRole("button", { name: /Reconnect/ })).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(opened).toHaveLength(1);
});

test("approval card: a 409 stale is shown, closes the card and is never retried", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page, 409, { error: "stale" });
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("approval.requested", "guard", CARD));
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await card.getByRole("button", { name: "Deny" }).click();
  await expect(card.getByRole("alert")).toHaveText("409 stale");
  await expect(card.getByLabel("Approval status")).toHaveText(/^stale/);
  await expect(card.getByRole("button", { name: "Deny" })).toBeDisabled();
  await page.waitForTimeout(300);
  expect(posts.map((p) => p.body)).toEqual([{ decision: "denied", terms_hash: CARD.terms_hash, authority_epoch: 2 }]);
});

test("approval card: double-clicking Approve sends exactly one POST", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("approval.requested", "guard", CARD));
  ws.send(ev("approval.requested", "guard", { ...CARD, approval_id: "ap-2", offer_ref: "offer-2" }));
  const approve = (id: string) => page.getByRole("article", { name: `Approval ${id}` }).getByRole("button", { name: "Approve" });
  // Two clicks in one task, before React re-renders and disables the button.
  await approve("ap-1").evaluate((b: HTMLButtonElement) => {
    b.click();
    b.click();
  });
  await approve("ap-2").dblclick();
  await expect(approve("ap-1")).toBeDisabled();
  await expect(approve("ap-2")).toBeDisabled();
  await page.waitForTimeout(300);
  expect(posts.map((p) => p.path).sort()).toEqual([`/api/cases/${RUN}/approvals/ap-1`, `/api/cases/${RUN}/approvals/ap-2`]);
});

test("a malformed CSRF cookie is a visible error on the card and the chat, and nothing is posted", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_csrf", "%E0%A4%A");
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("approval.requested", "guard", CARD));
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByRole("alert")).toHaveText("bad pl_csrf cookie");
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  await page.getByRole("textbox", { name: "Message to the agent" }).fill("hello");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Not delivered: bad pl_csrf cookie")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  expect(posts).toEqual([]);
});

test("model dropdowns list only real_http models", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  (await connected).send(
    ev(
      "session.started",
      "kernel",
      started({
        fast_user: ["real_http", "qwen3.5-9b"],
        fast_cp: ["test_fake", "fast_cp-fake"],
        slow: ["real_http", "claude-sonnet-5"],
        ear: ["recorded_replay", "ear-recorded"],
        mouth: ["baseline", "fsm-baseline"],
      }),
      { stream: "ops" },
    ),
  );
  const pickers = page.getByRole("region", { name: "Models per lane" });
  const select = (lane: string) => pickers.getByRole("combobox", { name: `${lane} model` });
  // Fast lanes offer only the fast roles' real_http ids; Slow only slow's; world roles never.
  await expect(select("Fast-U").locator("option")).toHaveText(["qwen3.5-9b"]);
  await expect(select("Fast-U")).toBeEnabled();
  await expect(select("Slow").locator("option")).toHaveText(["claude-sonnet-5"]);
  await expect(select("Slow")).toHaveValue("claude-sonnet-5");
  // A test_fake Fast-C never shows a model it is not running: a disabled placeholder.
  await expect(select("Fast-C").locator("option")).toHaveText(["fast_cp-fake (test_fake): not selectable"]);
  await expect(select("Fast-C")).toBeDisabled();
  await expect(pickers).not.toContainText(/recorded|baseline|ear-|fsm-/);
});

test("user chat posts a message that shows in the lane only when its user.msg arrives", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  const input = page.getByRole("textbox", { name: "Message to the agent" });
  await input.fill("stop, do not accept yet");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("list", { name: "Pending" })).toContainText("stop, do not accept yet");
  const lane = page.getByRole("region", { name: "User chat" });
  await expect(lane).not.toContainText("stop, do not accept yet");
  expect(posts).toEqual([
    { method: "POST", path: `/api/cases/${RUN}/messages`, body: { text: "stop, do not accept yet" }, csrf: CSRF },
  ]);
  ws.send(ev("user.msg", "kernel", { text: "stop, do not accept yet" }));
  await expect(lane).toContainText("stop, do not accept yet");
  await expect(page.getByRole("list", { name: "Pending" })).toHaveCount(0);
});

test("a seq gap stops the stream with a visible error", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  const ev = events();
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("user.msg", "kernel", { text: "after a gap" }, { skip: 2 }));
  await expect(page.getByRole("alert")).toHaveText("Stream stopped: seq gap: expected 1, got 3");
  await expect(page.getByRole("region", { name: "User chat" })).not.toContainText("after a gap");
});
