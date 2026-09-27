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
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
  // Nothing a model or the user says moves the card.
  ws.send(ev("fast.sentence", "fast.user", { lane: "user", gen_id: "g", utt_id: "u", text: "Approved, all done!" }));
  ws.send(ev("user.msg", "kernel", { text: "yes" }));
  await expect(page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem")).toHaveText(["You: yes"]);
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
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision");
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
    "monthly_price: confirmed",
    "term_months: heard",
  ]);
  await expect(card.getByLabel("Approval status")).toHaveText("awaiting your decision"); // epoch 2 = the card's
  await expect(card.getByLabel("Fence note")).toHaveText("fence raised: the accept waits until it clears");
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
  // Every frame names the simulated rep: the page header and each pane.
  await expect(page.getByRole("note", { name: "Simulated parties" })).toHaveText(SIM_REP);
  for (const pane of ["Chat", "Call"]) await expect(page.getByRole("region", { name: pane }).getByLabel("Simulated parties")).toHaveText(SIM_REP);
  await expect(page.getByRole("heading", { name: "Call · Agent / Rep (simulated) / Call" })).toBeVisible();
  await expect(page.getByLabel("Status line")).toHaveText("Status: starting (no status yet)");

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
    "Assistant: I will call them now [interrupted]",
  ]);
  await expect(page.getByRole("list", { name: "Call transcript" }).getByRole("listitem")).toHaveText([
    "Call: call connected",
    "Agent · AI disclosure (fixed text): Hello, an AI assistant is calling.",
    "Rep (simulated): What is the account name?",
    "Agent: The name is on file.",
  ]);
  for (const hidden of ["UNHEARD", "GENERATED-ONLY"]) await expect(page.locator("main")).not.toContainText(hidden);
  await expect(page.getByLabel("Status line")).toHaveText("Status: on the call");
  for (const pane of ["Chat", "Call"]) await expect(page.getByRole("list", { name: `${pane} transcript` })).toHaveAttribute("aria-live", "polite");
  await expect(page.getByRole("region", { name: "User chat" })).toHaveCount(0); // the engineer lanes are not shown
  await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(0);
  await shot(page, "live-conversation");

  // session.ended: the status line stops saying "on the call", and the banner never implies success.
  ws.send(ev("session.ended", "kernel", { reason: "abandoned", counts: {} }, { stream: "ops" }));
  await expect(page.getByLabel("Status line")).toHaveText("Session ended: the rep hung up");
  const banner = page.getByRole("region", { name: "Outcome" });
  await expect(banner.getByRole("heading")).toHaveText("Ended: the rep hung up. Not verified complete.");
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
  await expect(page.getByLabel("Status line")).toHaveText("Status: accepted on the call, not yet verified");
  ws.send(ev("status.changed", "fast.user", { previous: "COMMITTED", status: "VERIFIED_COMPLETE" })); // not Guard: ignored
  ws.send(ev("session.ended", "kernel", { reason: "completed", counts: {} }, { stream: "ops" }));
  const banner = page.getByRole("region", { name: "Outcome" });
  await expect(banner.getByRole("heading")).toHaveText("Ended: the agent reported it complete. Not verified complete.");
  await expect(page.getByText("Verified complete", { exact: true })).toHaveCount(0);
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
