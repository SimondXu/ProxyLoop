import { expect, test, type Page } from "@playwright/test";
import { capturePosts, CSRF, csrfCookie, events, mockSockets, RUN, shot, started } from "./liveMock";

const REAL: Record<string, [string, string]> = {
  fast_user: ["real_http", "qwen3.5-9b"],
  fast_cp: ["real_http", "qwen3.5-9b"],
  slow: ["real_http", "claude-sonnet-5"],
};
/** The authority strip sits behind a disclosure in the sticky header: open it (idempotent). */
async function authority(page: Page) {
  await page.locator("details.authority").evaluate((d: HTMLDetailsElement) => (d.open = true));
  return page.getByRole("region", { name: "Authority" });
}
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
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision");
  // Nothing a model or the user says moves the card.
  ws.send(ev("fast.sentence", "fast.user", { lane: "user", gen_id: "g", utt_id: "u", text: "Approved, all done!" }));
  ws.send(ev("user.msg", "kernel", { text: "yes" }));
  const chatItems = page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem");
  await expect(chatItems.filter({ hasNot: page.getByRole("article") })).toHaveText(["You: yes"]);
  // The card sits in the chat stream at its event's seq: before the later message.
  await expect(chatItems.first().getByRole("article", { name: "Approval ap-1" })).toBeVisible();
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision");
  await shot(page, "live-card");

  await card.getByRole("button", { name: "Approve" }).click();
  await expect(card.getByLabel("Approval status")).toHaveText("Sent. Waiting for Guard to record it");
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
  await expect(card.getByLabel("Approval status")).toHaveText(/^You approved · \d{1,2}:\d{2}\s[AP]M$/);
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
  await expect(card.getByLabel("Approval status")).toHaveText("Sent. Waiting for Guard to record it");
  expect(posts).toHaveLength(1);
  const denied = JSON.parse(ev("action.denied", "kernel", { intent: "approval.post", reason: "fence_raised" }));
  ws.send(JSON.stringify({ ...denied, cause_ids: [JSON.parse(requested).event_id] }));
  await expect(card.getByLabel("Approval status")).toHaveText("Not accepted by the system: your new message came first");
  await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
  await expect(card.getByRole("button", { name: "Decline" })).toBeDisabled();
});

test("a socket refused or unreachable before it opens (1006) says so, with no reconnect", async ({ page }) => {
  // The e2e server is the real API, which has /ws: the refused upgrade is mocked
  // as the browser reports one, a 1006 close before open.
  const opened: string[] = [];
  await page.routeWebSocket(/\/ws\//, (ws) => {
    opened.push(ws.url());
    ws.close({ code: 1006 });
  });
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
  await card.getByRole("button", { name: "Decline" }).click();
  await expect(card.getByRole("alert")).toHaveText("409 stale");
  await expect(card.getByLabel("Approval status")).toHaveText(/^No longer valid/);
  await expect(card.getByRole("button", { name: "Decline" })).toBeDisabled();
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
  const B = { ...CARD, approval_id: "ap-2", offer_ref: "offer-2", terms_hash: "b2b2b2b2b2b2b2b2" };
  ws.send(ev("approval.requested", "guard", B));
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
  // I6 (#136 N5): each card posts its own terms hash and epoch.
  const body = (id: string) => posts.find((p) => p.path.endsWith(`/${id}`))?.body;
  expect([body("ap-1"), body("ap-2")]).toEqual([
    { decision: "granted", terms_hash: CARD.terms_hash, authority_epoch: 2 },
    { decision: "granted", terms_hash: B.terms_hash, authority_epoch: 2 },
  ]);
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
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision");
  await page.getByRole("textbox", { name: "Message to the assistant" }).fill("hello");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Not delivered: bad pl_csrf cookie")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send" })).toBeEnabled();
  expect(posts).toEqual([]);
});

test("the live page shows the session's models read-only, with their kind: they are chosen on the start page", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  (await connected).send(
    ev("session.started", "kernel", started({ fast_user: ["real_http", "qwen3.5-9b"], fast_cp: ["test_fake", "fast_cp-fake"] }), {
      stream: "ops",
    }),
  );
  const models = page.getByRole("list", { name: "Models" });
  await expect(models.getByRole("listitem")).toHaveText(["fast_user: real_http qwen3.5-9b", "fast_cp: test_fake fast_cp-fake"]);
  await expect(page.getByRole("combobox")).toHaveCount(0);
});

test("the authority strip and the card's read-back progress follow the fixed emitters' events", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  const strip = await authority(page);
  await expect(strip).toHaveText(/status no status\.changed yet.*fence none.*epoch 0/);
  ws.send(ev("status.changed", "guard", { previous: "INTAKE", status: "IN_CALL" }));
  ws.send(ev("readback.updated", "guard", { offer_ref: "offer-1", revision: 1, slot_statuses: { monthly_price: "heard", term_months: "unknown" } }));
  ws.send(ev("approval.requested", "guard", CARD));
  ws.send(ev("readback.updated", "guard", { offer_ref: "offer-1", revision: 1, slot_statuses: { monthly_price: "confirmed", term_months: "heard" } }));
  ws.send(ev("status.changed", "fast.user", { previous: "IN_CALL", status: "VERIFIED_COMPLETE" })); // not Guard: ignored
  ws.send(ev("authority.fence", "kernel", { op: "raised", fence_id: "fence-1", utt_id: `${RUN}:0` }));
  ws.send(ev("speak.revoked", "kernel", { lane: "cp", reason: "fence" }));
  ws.send(ev("action.denied", "kernel", { intent: "accept_offer", reason: "fence_raised" }));
  ws.send(ev("authority.epoch", "kernel", { new: 2, reason: "f2s_revoke" }));
  await expect(strip.getByLabel("Case status")).toHaveText("status IN_CALL");
  await expect(strip.getByLabel("Fence")).toHaveText("fence raised (fence-1)");
  await expect(strip.getByLabel("Epoch")).toHaveText("epoch 2");
  await expect(strip.getByLabel("Last revoked")).toHaveText("last speak.revoked fence (kernel)");
  await expect(strip.getByLabel("Last denied")).toHaveText("last action.denied accept_offer: fence_raised (kernel)");
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await expect(card.getByRole("list", { name: "Read-back progress" }).getByRole("listitem")).toHaveText([
    "Monthly price Read back",
    "Contract length Heard, not read back",
  ]);
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision"); // epoch 2 = the card's
  await expect(card.getByLabel("Fence note")).toHaveText("Paused: reading your new message before anything is accepted.");
  await shot(page, "live-strip-mock");
  ws.send(ev("authority.fence", "kernel", { op: "cleared", fence_id: "fence-1", utt_id: `${RUN}:0` }));
  await expect(strip.getByLabel("Fence")).toHaveText("fence cleared (fence-1)");
  await expect(card.getByLabel("Fence note")).toHaveCount(0);
});

test("a /ws/live frame of another run stops the stream (#136 N4)", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  ws.send(events()("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(events("other-run")("user.msg", "kernel", { text: "not this run" }, { skip: 1 }));
  await expect(page.getByRole("alert")).toHaveText(`Stream stopped: frame of run other-run, not ${RUN}`);
  await expect(page.getByRole("region", { name: "Chat" })).not.toContainText("not this run");
});

test("user chat posts a message that shows in the lane only when its user.msg arrives", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  const input = page.getByRole("textbox", { name: "Message to the assistant" });
  await input.fill("stop, do not accept yet");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("list", { name: "Pending" })).toContainText("stop, do not accept yet");
  const lane = page.getByRole("list", { name: "Chat transcript" });
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
  await expect(page.getByRole("region", { name: "Chat" })).not.toContainText("after a gap");
});

const SIM: Record<string, [string, string]> = { ...REAL, ear: ["real_http", "gemini-3.8-flash"], mouth: ["real_http", "gemini-3.8-flash"] };
const SIM_REP = "Simulated rep; no real company was called";

test("conversation view: two panes with the right speakers, heard text only, the sim labels, the status line and the banner", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(SIM), { stream: "ops" }));
  // Every frame names the simulated rep: the page header and the call column; the chat column names only a simulated user.
  await expect(page.getByRole("note", { name: "Simulated parties" })).toHaveText(SIM_REP);
  await expect(page.getByRole("region", { name: "Call" }).getByLabel("Simulated parties")).toHaveText(SIM_REP);
  await expect(page.getByRole("region", { name: "Chat" }).getByLabel("Simulated parties")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Call with the company" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Call" })).toContainText("Rep (simulated)");
  await expect(page.getByLabel("Status line")).toHaveText("Getting the details before calling");
  await expect(page.getByText("Planner is listening")).toBeVisible(); // outside the live region

  const opened = JSON.parse(ev("chan.opened", "kernel", { lane: "cp" })) as { event_id: string };
  ws.send(JSON.stringify(opened));
  ws.send(ev("status.changed", "guard", { previous: "INTAKE", status: "IN_CALL" }));
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "disclosure", text: "Hello, an AI assistant is calling." });
  ws.send(said);
  const released = ev("speak.released", "kernel", { lane: "cp" });
  const causedBy = (frame: string, cause: string) => JSON.stringify({ ...JSON.parse(frame), cause_ids: [(JSON.parse(cause) as { event_id: string }).event_id] });
  ws.send(causedBy(released, said));
  const heard = (lane: string, generated: string, text: string) =>
    ev("utt.delivered", "kernel", { lane, utt_id: "u", text_generated: generated, text_heard: text, interrupted: generated !== text });
  ws.send(causedBy(heard("cp", "Hello, an AI assistant is calling.", "Hello, an AI assistant is calling."), released));
  ws.send(ev("user.msg", "kernel", { text: "Please lower my bill." }));
  ws.send(ev("fast.sentence", "fast.user", { lane: "user", gen_id: "g", utt_id: "u", text: "UNHEARD sentence" }));
  ws.send(heard("user", "I will call them now and GENERATED-ONLY tail.", "I will call them now"));
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", utt_id: "cp-1", text: "What is the account name?" }));
  ws.send(heard("cp", "The name is on file.", "The name is on file."));

  await expect(page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem")).toHaveText([
    "You: Please lower my bill.",
    "Assistant: I will call them now — cut off",
  ]);
  await expect(page.getByRole("list", { name: "Call transcript" }).getByRole("listitem")).toHaveText([
    "Call: call connected",
    "Agent: Hello, an AI assistant is calling. AI disclosure · fixed wording",
    "Rep (simulated): What is the account name?",
    "Agent: The name is on file.",
  ]);
  for (const hidden of ["UNHEARD", "GENERATED-ONLY"]) await expect(page.locator("main")).not.toContainText(hidden);
  await expect(page.getByLabel("Status line")).toHaveText("On the call with the company");
  // The rail's steps: fixed wording from Guard's and the kernel's events, never a line's text.
  await expect(page.getByRole("region", { name: "Steps" }).getByRole("listitem")).toHaveText([
    /^Call \d{2}:\d{2} Called the company$/,
    /^Guard \d{2}:\d{2} Opened with the AI disclosure$/,
  ]);
  for (const pane of ["Chat", "Call"]) await expect(page.getByRole("list", { name: `${pane} transcript` })).toHaveAttribute("aria-live", "polite");
  await expect(page.getByRole("region", { name: "User chat" })).toHaveCount(0); // the engineer lanes are not shown
  await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(0);
  await shot(page, "live-conversation");

  // session.ended: the status line stops saying "on the call", and the banner never implies success.
  ws.send(ev("session.ended", "kernel", { reason: "abandoned", counts: {} }, { stream: "ops" }));
  await expect(page.getByLabel("Status line")).toHaveText("The rep ended the call.");
  // The receipt is the chat's last item, at session.ended's seq.
  const banner = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
  await expect(banner.getByRole("heading")).toHaveText("The rep ended the call.");
  await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(1); // the chat's receipt only: none in the rail
  await expect(page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem").last().getByRole("region", { name: "Outcome" })).toBeVisible();
  await expect(banner).toContainText("Reason: abandoned · last case status: IN_CALL");
  await expect(banner).not.toContainText("on the call");
  await shot(page, "live-ended");
});

test("conversation view: Verified complete only on Guard's VERIFIED_COMPLETE", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  await expect(page.getByLabel("Simulated parties")).toHaveCount(0); // no world rep, no sim user: no sim label
  ws.send(ev("status.changed", "guard", { previous: "COMMIT_AUTHORIZED", status: "COMMITTED" }));
  await expect(page.getByLabel("Status line")).toHaveText("Accepted on the call. Checking the simulated company's records…");
  ws.send(ev("status.changed", "fast.user", { previous: "COMMITTED", status: "VERIFIED_COMPLETE" })); // not Guard: ignored
  ws.send(ev("session.ended", "kernel", { reason: "completed", counts: {} }, { stream: "ops" }));
  const banner = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
  await expect(banner.getByRole("heading")).toHaveText("Accepted on the call. Not verified yet.");
  await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(1);
  await expect(page.getByText("Verified complete", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Done. Verified.", { exact: true })).toHaveCount(0);
});

test("conversation view: each pane follows the newest line until the reader scrolls up, then offers Jump to latest", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  const chat = page.getByRole("list", { name: "Chat transcript" });
  const pane = page.getByRole("region", { name: "Chat" });
  const gap = () => chat.evaluate((el) => el.scrollHeight - el.scrollTop - el.clientHeight);
  for (let i = 1; i <= 60; i++) ws.send(ev("user.msg", "kernel", { text: `message ${i}` }));
  await expect(chat.getByRole("listitem").last()).toHaveText("You: message 60");
  await expect(chat.getByRole("listitem").last()).toBeInViewport();
  expect(await gap()).toBeLessThanOrEqual(8);
  await expect(pane.getByRole("button", { name: "Jump to latest" })).toHaveCount(0);

  await chat.evaluate((el) => el.scrollTo(0, 0));
  await expect(pane.getByRole("button", { name: "Jump to latest" })).toBeVisible();
  ws.send(ev("user.msg", "kernel", { text: "message 61" }));
  await expect(chat.getByRole("listitem").last()).toHaveText("You: message 61");
  await expect(chat.getByRole("listitem").first()).toBeInViewport(); // the reader's place is kept
  await pane.getByRole("button", { name: "Jump to latest" }).click();
  await expect(chat.getByRole("listitem").last()).toBeInViewport();
  await expect(pane.getByRole("button", { name: "Jump to latest" })).toHaveCount(0);
  ws.send(ev("user.msg", "kernel", { text: "message 62" }));
  await expect(chat.getByRole("listitem").last()).toHaveText("You: message 62");
  await expect(chat.getByRole("listitem").last()).toBeInViewport();
});

test("?view=engineer shows the six lanes and the God-view; the view links switch in place on one socket", async ({ page }) => {
  const { urls, connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}&view=engineer`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("user.msg", "kernel", { text: "hello lanes" }));
  for (const lane of ["User chat", "Rep", "Fast-U", "Fast-C", "Slow", "Guard"]) await expect(page.getByRole("region", { name: lane })).toBeVisible();
  await expect(page.getByRole("region", { name: "User chat" }).getByRole("article", { name: /^user\.msg #/ })).toContainText("hello lanes");
  await expect(page.getByRole("checkbox", { name: "God-view" })).toBeVisible();
  await expect(page.getByLabel("Status line")).toBeVisible();
  await shot(page, "live-engineer");

  await page.getByRole("link", { name: "Conversation view" }).click();
  await expect(page).toHaveURL(`/?live=${RUN}`);
  await expect(page.getByRole("list", { name: "Chat transcript" })).toContainText("You: hello lanes");
  await expect(page.getByRole("region", { name: "Fast-U" })).toHaveCount(0);
  await page.getByRole("link", { name: "Engineer view" }).click();
  await expect(page).toHaveURL(`/?live=${RUN}&view=engineer`);
  await expect(page.getByRole("region", { name: "Fast-U" })).toBeVisible();
  expect(urls).toHaveLength(1);
});

const MANDATE = {
  mandate_id: "m-1",
  mandate_hash: "a".repeat(64),
  status: "proposed",
  epoch: 1,
  max_monthly_price_minor: 6500,
  max_term_months: 24,
  max_one_time_fees_minor: 0,
  required_features: [],
  forbidden_changes: [],
  expires_ms: null,
  decided_by: null,
};

test("limits card: confirmed only by a click, one POST through the mandate route, decided only by the kernel; the grant stales an open approval card", async ({
  page,
  baseURL,
}) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page, 200, { status: "posted" });
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("authority.epoch", "kernel", { new: 1, reason: "slow_revoke" }));
  ws.send(ev("mandate.proposed", "guard", MANDATE));
  ws.send(ev("approval.requested", "guard", { ...CARD, authority_epoch: 1, binding: { ...CARD.binding, authority_epoch: 1 } }));
  const limits = page.getByRole("article", { name: "Limits m-1" });
  const status = limits.getByLabel("Limits status");
  await expect(status).toHaveText("Waiting for your confirmation");
  await expect(limits.getByRole("definition")).toHaveText(["up to $65.00", "up to 24 months", "up to $0.00"]);
  // The limits and the approval card sit in the chat column, not in the sticky header.
  await expect(page.getByRole("region", { name: "Chat" }).getByRole("article")).toHaveCount(2);
  // A model's text or a mandate.decided from another actor moves nothing.
  ws.send(ev("fast.sentence", "fast.user", { lane: "user", gen_id: "g", utt_id: "u", text: "Your limits are confirmed!" }));
  ws.send(ev("mandate.decided", "slow", { mandate_id: "m-1", mandate_hash: MANDATE.mandate_hash, decision: "granted", by: "ui" }));
  await expect(status).toHaveText("Waiting for your confirmation");
  await shot(page, "live-limits-card");

  const confirm = limits.getByRole("button", { name: "Confirm limits" });
  await confirm.evaluate((b: HTMLButtonElement) => {
    b.click();
    b.click();
  });
  await expect(status).toHaveText("Sent. Waiting for Guard to record it");
  await page.waitForTimeout(300);
  expect(posts).toEqual([
    {
      method: "POST",
      path: `/api/cases/${RUN}/mandates/m-1`,
      body: { decision: "granted", mandate_hash: MANDATE.mandate_hash, authority_epoch: 1 },
      csrf: CSRF,
    },
  ]);
  ws.send(ev("approval.post", "ui", { subject: "mandate", subject_id: "m-1", decision: "granted", subject_hash: MANDATE.mandate_hash, authority_epoch: 1 }));
  ws.send(ev("mandate.decided", "kernel", { mandate_id: "m-1", mandate_hash: MANDATE.mandate_hash, decision: "granted", by: "ui" }));
  ws.send(ev("authority.epoch", "kernel", { new: 2, reason: "mandate_decided" }));
  await expect(status).toHaveText(/^Confirmed by you/);
  await expect(limits.getByRole("button")).toHaveCount(0);
  // The grant bumped the epoch: the open approval card is stale, not an error.
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await expect(card.getByLabel("Approval status")).toHaveText("No longer valid: your instructions changed");
  await expect(card.getByRole("alert")).toHaveCount(0);
  expect(posts).toHaveLength(1);
});

test("limits card: a 409 stale is shown in words and never retried", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page, 409, { error: "stale", reason: "stale_epoch" });
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("authority.epoch", "kernel", { new: 1, reason: "slow_revoke" }));
  ws.send(ev("mandate.proposed", "guard", MANDATE));
  const limits = page.getByRole("article", { name: "Limits m-1" });
  await limits.getByRole("button", { name: "Not these" }).click();
  await expect(limits.getByRole("alert")).toHaveText("409 stale: stale_epoch");
  await expect(limits.getByLabel("Limits status")).toHaveText("No longer valid: your instructions changed");
  await page.waitForTimeout(300);
  expect(posts.map((p) => p.body)).toEqual([{ decision: "denied", mandate_hash: MANDATE.mandate_hash, authority_epoch: 1 }]);
});

test("approval card: a fence pauses a granted accept, and a fence revoke says the yes was never said", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("approval.requested", "guard", CARD));
  const granted = ev("approval.decided", "kernel", { approval_id: "ap-1", decision: "granted", by: "ui" });
  ws.send(granted);
  // Guard's authorization cites the grant it rests on (slow/authority.py accept_offer).
  const authorized = JSON.parse(ev("action.authorized", "guard", { intent: {}, capability: { cap_id: "cap-1", terms_hash: CARD.terms_hash, epoch: 2 } }));
  ws.send(JSON.stringify({ ...authorized, cause_ids: [JSON.parse(granted).event_id] }));
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: "cap-1" });
  ws.send(said);
  ws.send(ev("authority.fence", "kernel", { op: "raised", fence_id: "fence-1", utt_id: `${RUN}:9` }));
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await expect(card.getByLabel("Approval status")).toHaveText(/^You approved · \d{1,2}:\d{2}\s[AP]M$/);
  await expect(card.getByLabel("Fence note")).toHaveText("Paused: reading your new message before anything is accepted.");
  const revoked = JSON.parse(ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: "cap-1" }));
  ws.send(JSON.stringify({ ...revoked, cause_ids: [JSON.parse(said).event_id] }));
  await expect(card.getByRole("note")).toHaveText("Stopped. The yes was never said to the rep.");
  await expect(card.getByLabel("Fence note")).toHaveCount(0);
});

// S1-SYS-51: the receipt, in the chat at session.ended, for every variant.
const SPEND = { priced_micro_usd: 12_345, priced_by_role: {}, unpriced_calls: 3, unpriced_by_role: {}, gpu_time_calls: 0, tokens: 900 };
const OFFER = {
  offer_ref: "offer-1",
  revision: 1,
  terms_hash: CARD.terms_hash,
  slots: [
    { field: "monthly_price", value: "7500", unit: "usd_minor", status: "confirmed" },
    { field: "term_months", value: "12", unit: "months", status: "confirmed" },
    { field: "fees_none", value: "false", unit: "bool", status: "heard" },
    { field: "fee:activation", value: "2000", unit: "usd_minor", status: "heard" },
    { field: "expires", value: "none", unit: "iso", status: "confirmed" },
  ],
};

test("receipt: Done. Verified. with the accepted terms, the confirmation, the verifier and your approval; the cost under details", async ({
  page,
}) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ev = events();
  const ws = await connected;
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("offer.recorded", "guard", OFFER));
  ws.send(ev("approval.requested", "guard", CARD));
  const granted = ev("approval.decided", "kernel", { approval_id: "ap-1", decision: "granted", by: "ui" });
  ws.send(granted);
  // Guard's authorization cites the grant it rests on (slow/authority.py accept_offer).
  const authorized = JSON.parse(ev("action.authorized", "guard", { intent: {}, capability: { cap_id: "cap-1", terms_hash: CARD.terms_hash, epoch: 2 } }));
  ws.send(JSON.stringify({ ...authorized, cause_ids: [JSON.parse(granted).event_id] }));
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: "cap-1" });
  ws.send(said);
  const released = JSON.parse(ev("speak.released", "kernel", { lane: "cp", cap_id: "cap-1" }));
  ws.send(JSON.stringify({ ...released, cause_ids: [JSON.parse(said).event_id] }));
  ws.send(ev("evidence.recorded", "guard", { evidence_id: "ledger:CNF-8841", kind: "ledger", confirmation_id: "CNF-8841" }));
  ws.send(ev("completion.decided", "guard", { verdict: "ok", reasons: [] }));
  ws.send(ev("status.changed", "guard", { previous: "EVIDENCE_PENDING", status: "VERIFIED_COMPLETE" }));
  ws.send(ev("session.ended", "kernel", { reason: "completed", counts: {}, spend: SPEND }, { stream: "ops" }));

  const receipt = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
  await expect(receipt.getByRole("heading")).toHaveText("Done. Verified.");
  await expect(receipt.getByRole("list", { name: "Accepted terms" }).getByRole("listitem")).toHaveText([
    "Monthly price $75.00 Read back",
    "Contract length 12 months Read back",
    "One-time fees apply Heard, not read back",
    "Fee: activation $20.00 Heard, not read back",
    "No expiry date Read back",
  ]);
  await expect(receipt.getByText("Confirmation CNF-8841", { exact: true })).toBeVisible();
  await expect(receipt.getByText("Verified against the simulated company's records", { exact: true })).toBeVisible();
  await expect(receipt.getByText(/^Approved by you at \d{1,2}:\d{2}\s[AP]M$/)).toBeVisible();
  // The cost: session.ended's spend, formatted, behind a collapsed details; never a saving.
  const cost = receipt.getByRole("list", { name: "Cost" });
  await expect(cost).toBeHidden();
  await receipt.getByText("Cost and details", { exact: true }).click();
  await expect(cost.getByRole("listitem")).toHaveText(["Priced model calls: $0.012345", "3 calls unpriced"]);
  await expect(receipt).not.toContainText(/sav/i);
  await shot(page, "receipt-verified");
});

const VARIANTS: [slug: string, status: string, reason: string, heading: string][] = [
  ["committed", "COMMITTED", "completed", "Accepted on the call. Not verified yet."],
  ["no-deal", "VERIFIED_NO_DEAL", "no_deal", "No deal. Nothing was accepted."],
  ["info-only", "CLOSED_NO_ACTION", "info_only", "Here's what they offered · nothing accepted (information only)"],
  ["abandoned", "ABANDONED", "abandoned", "The rep ended the call."],
  ["timeout", "IN_CALL", "timeout", "Stopped: the session timed out. Not completed."],
  ["stopped", "IN_CALL", "stopped", "Stopped: the session was stopped. Not completed."],
  ["endpoint", "IN_CALL", "llm_unavailable", "A model endpoint stopped responding, so the case stopped. ProxyLoop never switches to a backup model."],
  ["unknown", "IN_CALL", "brand_new_reason", "Ended: brand_new_reason. Not verified complete."],
];
for (const [slug, status, reason, heading] of VARIANTS) {
  test(`receipt: ${slug} (${status}, session.ended{${reason}})`, async ({ page }) => {
    const { connected } = await mockSockets(page);
    await page.goto(`/?live=${RUN}`);
    const ev = events();
    const ws = await connected;
    ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
    ws.send(ev("offer.recorded", "guard", OFFER));
    ws.send(ev("offer.recorded", "guard", { ...OFFER, revision: 2, slots: OFFER.slots.slice(0, 2) }));
    ws.send(ev("status.changed", "guard", { previous: "IN_CALL", status }));
    ws.send(ev("session.ended", "kernel", { reason, counts: {}, spend: { ...SPEND, unpriced_calls: 0 } }, { stream: "ops" }));
    const receipt = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
    await expect(receipt.getByRole("heading")).toHaveText(heading);
    await expect(receipt).not.toContainText("Verified against");
    // No deal and information only list each offer's latest revision with its read-back status.
    const offers = receipt.getByRole("list", { name: /^Offer / });
    if (slug === "no-deal" || slug === "info-only") {
      await expect(offers).toHaveCount(1);
      await expect(receipt.getByRole("list", { name: "Offer offer-1, revision 2" }).getByRole("listitem")).toHaveText([
        "Monthly price $75.00 Read back",
        "Contract length 12 months Read back",
      ]);
    } else await expect(offers).toHaveCount(0);
    await receipt.getByText("Cost and details", { exact: true }).click();
    await expect(receipt.getByRole("list", { name: "Cost" }).getByRole("listitem")).toHaveText(["Priced model calls: $0.012345"]);
    await shot(page, `receipt-${slug}`);
  });
}

// S1-SYS-65: the principal's role card, folded in the rail, from GET /api/cases/{case}/card (a synthetic card).
const ROLE = {
  company: "Example Mobile",
  persona: "Sam Doe, a teacher.",
  goal: "Pay at most 60 dollars a month.",
  facts: [
    { key: "account.holder_name", value: "Sam Doe", identity: true, shareable: true },
    { key: "budget.max_monthly_usd", value: "60", identity: false, shareable: false },
  ],
  approval: { max_monthly_price_usd: "64.00", max_term_months: 12, max_one_time_fees_usd: "0" },
  stop: null,
};

test("your role: the live page folds the case's role card, read with GET only", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { connected } = await mockSockets(page);
  const asked: string[] = [];
  await page.route(`**/api/cases/${RUN}/card`, (route) => {
    asked.push(route.request().method());
    return route.fulfill({ status: 200, json: ROLE });
  });
  await page.goto(`/?live=${RUN}`);
  (await connected).send(events()("session.started", "kernel", started(REAL), { stream: "ops" }));
  const role = page.locator("details.pl-role");
  await expect(role.locator("summary")).toHaveText("Your role");
  await expect(role).not.toHaveAttribute("open"); // folded until the user opens it
  await role.locator("summary").click();
  await expect(role).toContainText("Sam Doe, a teacher.");
  await expect(role).toContainText("Pay at most 60 dollars a month.");
  await expect(role.getByRole("heading", { name: "What you would approve" })).toBeVisible();
  await expect(role.locator("dl").nth(2)).toContainText("Monthly priceup to $64.00");
  expect(asked).toEqual(["GET"]);
});

test("your role: a refused card is shown as unavailable, never as an alert", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  await mockSockets(page);
  await page.route(`**/api/cases/${RUN}/card`, (route) => route.fulfill({ status: 403, json: { error: "csrf" } }));
  await page.goto(`/?live=${RUN}`);
  const role = page.locator("details.pl-role");
  await role.locator("summary").click();
  await expect(role).toContainText("Your role is unavailable: 403 csrf");
});
