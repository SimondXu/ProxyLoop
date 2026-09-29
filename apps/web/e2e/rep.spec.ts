import { expect, test } from "@playwright/test";
import { capturePosts, CSRF, csrfCookie, mockSockets, REP_CSRF, repFrames, RUN, shot } from "./liveMock";

const PRIVATE = ["walk-away floor is $60", "please keep it under $70", "offer rev 2 readback", "generated but cut"];

test("rep page: its own stream, only what the rep can hear, and it sends a rep utterance", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_rep_csrf", REP_CSRF);
  await csrfCookie(page, baseURL, "pl_csrf", CSRF); // the user's cookie, which the rep page must not use
  const { urls, connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?rep=${RUN}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("You're the rep on this call");
  await expect(page.getByRole("note")).toHaveText(
    "The caller is an AI agent (ProxyLoop) acting for a customer. You're playing the company's rep. This page shows only what's said on the call.",
  );
  const ws = await connected;
  const frame = repFrames();
  // Rebuilt frames, dense rep seqs. Private types pushed on the rep stream (even
  // claiming the cp lane) must still not show.
  ws.send(frame("chan.opened", { lane: "cp" }));
  ws.send(frame("user.msg", { lane: "cp", text: PRIVATE[1] }));
  ws.send(frame("summary.updated", { lane: "cp", scope: "private", text: PRIVATE[0] }));
  ws.send(frame("approval.requested", { lane: "cp", readback_text: PRIVATE[2] }));
  ws.send(frame("f2s.msg", { lane: "cp", text: PRIVATE[0] }));
  ws.send(frame("fast.sentence", { lane: "cp", text: "Hi, calling about the bill. generated but cut" }));
  ws.send(
    frame("utt.delivered", {
      lane: "cp",
      text_generated: "Hi, calling about the bill. generated but cut",
      text_heard: "Hi, calling about the bill.",
      interrupted: true,
    }),
  );
  ws.send(frame("utt.final", { lane: "cp", speaker: "partner", text: "We can do $75." }));

  const transcript = page.getByRole("list", { name: "Call transcript" });
  await expect(transcript.getByRole("listitem")).toHaveText([
    "Call: call connected",
    "The agent: Hi, calling about the bill. [interrupted]",
    "You: We can do $75.",
  ]);
  for (const text of PRIVATE) await expect(page.locator("body")).not.toContainText(text);
  await expect(page.locator("body")).not.toContainText(/qwen|real_http|Slow|Guard/);
  await expect(page.getByLabel("Connection")).toHaveText("open"); // no raw event count
  // S1-SYS-92: a v4 call card with two named voices, each over its own plain line (no bold prefix in a bubble); the
  // header holds the title and the Human rep mode chip, and the raw connection state sits folded under it.
  const call = page.getByRole("group", { name: "Call with the agent" });
  await expect(call.getByText("Connected", { exact: true })).toBeVisible();
  await expect(call.locator(".pl-who")).toHaveText(["The agent", "You"]);
  const ink = await call.locator(".pl-line-agent .pl-bubble").evaluate((el) => getComputedStyle(el).color);
  await expect(call.locator(".pl-line-rep .pl-bubble")).toHaveCSS("color", ink); // the rep's own lines at full ink, not dimmed
  await expect(call.locator("strong, b")).toHaveCount(0);
  await expect(call.getByText("The agent: the AI caller · You: the company's rep")).toBeVisible();
  const header = page.locator("header");
  await expect(header.getByText("Human rep mode", { exact: true })).toBeVisible();
  await expect(header).toHaveText("You're the rep on this callHuman rep mode");
  await expect(page.getByLabel("Connection")).toBeHidden(); // folded
  await page.getByText("Connection", { exact: true }).click();
  await expect(page.locator("details").filter({ has: page.getByLabel("Connection") }).getByLabel("Connection")).toBeVisible();

  const input = page.getByRole("textbox", { name: "Say to the agent" });
  await input.fill("Best I can do is $72.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("list", { name: "Pending" })).toContainText("Best I can do is $72.");
  expect(posts).toEqual([
    { method: "POST", path: `/api/cases/${RUN}/rep`, body: { text: "Best I can do is $72." }, csrf: REP_CSRF },
  ]);
  ws.send(frame("utt.final", { lane: "cp", speaker: "partner", text: "Best I can do is $72." }));
  await expect(transcript.getByRole("listitem").last()).toHaveText("You: Best I can do is $72.");
  await expect(page.getByRole("list", { name: "Pending" })).toHaveCount(0);
  await shot(page, "rep-page");

  expect(urls).toEqual([expect.stringMatching(new RegExp(`/ws/rep/${RUN}\\?from_seq=0$`))]);
  expect(urls.filter((u) => u.includes("/ws/live/"))).toEqual([]);
});

test("rep page: a 4403 close says not authorised, names /rep/{id}, and does not reconnect", async ({ page }) => {
  const { urls, connected } = await mockSockets(page);
  await page.goto(`/?rep=${RUN}`);
  (await connected).close({ code: 4403, reason: "role" });
  await expect(page.getByRole("alert")).toHaveText(
    `Stream stopped: not authorised (4403 role): open /rep/${RUN} from this origin`,
  );
  await expect(page.getByRole("button", { name: /Reconnect/ })).toHaveCount(0);
  await page.waitForTimeout(300);
  expect(urls).toHaveLength(1);
});

test("rep page: a gap in the rep stream's seq stops it with a visible error", async ({ page }) => {
  const { connected } = await mockSockets(page);
  await page.goto(`/?rep=${RUN}`);
  const ws = await connected;
  const frame = repFrames();
  ws.send(frame("chan.opened", { lane: "cp" }));
  ws.send(frame("utt.final", { lane: "cp", speaker: "partner", text: "after a gap" }, 1));
  await expect(page.getByRole("alert")).toHaveText("Stream stopped: seq gap: expected 1, got 2");
  await expect(page.getByRole("list", { name: "Call transcript" })).not.toContainText("after a gap");
});

test("rep page: the input waits for the kernel's call opening, and a 409 not_open says the call hasn't started, never retried", async ({
  page,
  baseURL,
}) => {
  await csrfCookie(page, baseURL, "pl_rep_csrf", REP_CSRF);
  const { connected } = await mockSockets(page);
  const posts = await capturePosts(page, 409, { error: "not_open" });
  await page.goto(`/?rep=${RUN}`);
  const ws = await connected;
  const frame = repFrames();
  const input = page.getByRole("textbox", { name: "Say to the agent" });
  const send = page.getByRole("button", { name: "Send" });
  await expect(input).toBeDisabled();
  await expect(send).toBeDisabled();
  await expect(input).toHaveAccessibleDescription("Waiting for the call to start");
  // Only the kernel's cp opening opens it: another lane's, or another actor's, does not.
  ws.send(frame("chan.opened", { lane: "user" }));
  ws.send(JSON.stringify({ ...JSON.parse(frame("chan.opened", { lane: "cp" })), actor: "fast.cp" }));
  ws.send(frame("utt.delivered", { lane: "cp", text_heard: "Hello, this is an AI agent calling for a customer." }));
  await expect(page.getByRole("list", { name: "Call transcript" }).getByRole("listitem")).toHaveText([
    "The agent: Hello, this is an AI agent calling for a customer.",
  ]);
  await expect(input).toBeDisabled();
  ws.send(frame("chan.opened", { lane: "cp" }));
  await expect(input).toBeEnabled();
  await expect(page.getByText("Waiting for the call to start")).toHaveCount(0);

  await input.fill("We can do $75.");
  await send.click();
  await expect(page.getByRole("alert")).toHaveText("The call hasn't started yet");
  await page.waitForTimeout(300);
  expect(posts).toHaveLength(1);
  await expect(input).toHaveValue("We can do $75."); // kept for the rep's own resend
  await shot(page, "rep-not-open");

  // The kernel's close disables it again.
  ws.send(frame("chan.closed", { lane: "cp" }));
  await expect(input).toBeDisabled();
  await expect(send).toBeDisabled();
  await expect(input).toHaveAccessibleDescription("The call has ended");
  expect(posts).toHaveLength(1);
});
