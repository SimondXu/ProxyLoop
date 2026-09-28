import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CSRF, csrfCookie, events, mockSockets, REP_CSRF, repFrames, RUN, shot, started } from "./liveMock";

// UI-8 (redesign §2.4, §3.6, §7 risk 10): axe on Start, Live (an open approval
// card and a limits card) and Rep, at desktop and phone sizes, 0 serious or
// critical; reduced motion; the phone's tabs and decision sheet.
const SIZES = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "phone", width: 390, height: 844 },
] as const;

const OPTIONS = {
  options: [
    { id: "vllm:q", lane: "fast_user", label: "Qwen", endpoint: "vllm", model_id: "qwen3.5-9b", default: true },
    { id: "vllm:qc", lane: "fast_cp", label: "Qwen", endpoint: "vllm", model_id: "qwen3.5-9b", default: true },
    { id: "tr:g", lane: "slow", label: "Gemini", endpoint: "teamrouter", model_id: "gemini-3.8-flash", default: true },
  ],
  tasks: ["cp-direct-discount"],
};
const REAL: Record<string, [string, string]> = {
  fast_user: ["real_http", "qwen3.5-9b"],
  fast_cp: ["real_http", "qwen3.5-9b"],
  slow: ["real_http", "claude-sonnet-5"],
  ear: ["test_fake", "sim-ear"],
  mouth: ["test_fake", "sim-mouth"],
};
const CARD = {
  approval_id: "ap-1",
  offer_ref: "offer-1",
  revision: 1,
  terms_hash: "3f2a9c01d4e5b6a7",
  readback_text: "Internet plan at $75/month for 12 months.\nNo other changes to the account.",
  authority_epoch: 0,
  expires_ms: 90_000,
  binding: { offer_ref: "offer-1", revision: 1, account_ref: "acct", principal_ref: "p", purpose: "retention", authority_epoch: 0 },
};
const OFFER = {
  offer_ref: "offer-1",
  revision: 1,
  terms_hash: CARD.terms_hash,
  slots: [
    { field: "monthly_price", value: "7500", unit: "usd_minor", status: "confirmed" },
    { field: "term_months", value: "12", unit: "months", status: "heard" },
  ],
};
const MANDATE = {
  mandate_id: "m-1",
  mandate_hash: "a".repeat(64),
  status: "proposed",
  epoch: 0,
  max_monthly_price_minor: 8000,
  max_term_months: 24,
  max_one_time_fees_minor: 0,
  required_features: [],
  forbidden_changes: [],
  expires_ms: null,
  decided_by: null,
};

/**
 * axe on the page at rest: entrance animations (finite) have run or were cancelled (their element left the
 * layout); the planner's pulse (infinite) is left alone.
 */
async function audit(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  const r = await new AxeBuilder({ page }).analyze();
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(bad.map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => `${n.target.join(" ")} ${n.failureSummary ?? ""}`).join("; ")}`)).toEqual([]);
}

/** A live page with the user's message, a call line, a limits card and an open approval card for $75/mo. */
async function liveWithCards(page: Page, baseURL: string | undefined) {
  await csrfCookie(page, baseURL, "pl_csrf", CSRF);
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  const ev = events();
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("user.msg", "kernel", { text: "Please lower my internet bill." }));
  ws.send(ev("status.changed", "guard", { previous: "INTAKE", status: "IN_CALL" }));
  ws.send(ev("chan.opened", "kernel", { lane: "cp" }));
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", text: "We can do $75 a month for 12 months." }));
  ws.send(ev("mandate.proposed", "guard", MANDATE));
  ws.send(ev("offer.recorded", "guard", OFFER));
  ws.send(ev("approval.requested", "guard", CARD));
  await expect(page.getByRole("article", { name: "Approval ap-1" }).getByLabel("Approval status")).toHaveText("Waiting for your decision");
  await expect(page.getByRole("article", { name: "Limits m-1" }).getByLabel("Limits status")).toHaveText("Waiting for your confirmation");
  return { ws, ev };
}

for (const size of SIZES) {
  test.describe(`axe at ${size.width}×${size.height}`, () => {
    test.use({ viewport: { width: size.width, height: size.height } });

    test("start page", async ({ page, baseURL }) => {
      await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
      await page.route("**/api/models", (route) => route.fulfill({ status: 200, json: OPTIONS }));
      await page.goto("/?start");
      await expect(page.getByRole("button", { name: /Start/ })).toBeEnabled();
      await audit(page);
      await shot(page, `a11y-start-${size.name}`);
    });

    test("live page with an open approval card and a limits card", async ({ page, baseURL }) => {
      await liveWithCards(page, baseURL);
      await audit(page);
      await shot(page, `a11y-live-${size.name}`);
    });

    test("rep page, before and after the call opens", async ({ page, baseURL }) => {
      await csrfCookie(page, baseURL, "pl_rep_csrf", REP_CSRF);
      const { connected } = await mockSockets(page);
      await page.goto(`/?rep=${RUN}`);
      const ws = await connected;
      await expect(page.getByRole("textbox", { name: "Say to the agent" })).toBeDisabled();
      await audit(page);
      const frame = repFrames();
      ws.send(frame("chan.opened", { lane: "cp" }));
      ws.send(frame("utt.delivered", { lane: "cp", text_heard: "Hi, calling about the bill." }));
      ws.send(frame("utt.final", { lane: "cp", speaker: "partner", text: "We can do $75." }));
      await expect(page.getByRole("list", { name: "Call transcript" }).getByRole("listitem")).toHaveCount(3);
      await audit(page);
      await shot(page, `a11y-rep-${size.name}`);
    });
  });
}

test.describe("phone (390×844)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the decision is a non-modal sheet on every tab, folds to a bar, and never takes focus", async ({ page, baseURL }) => {
    const { ws, ev } = await liveWithCards(page, baseURL);
    const tabs = page.getByRole("group", { name: "Show" });
    const card = page.getByRole("article", { name: "Approval ap-1" });
    await expect(tabs.getByRole("button", { name: "Chat" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("body")).toBeFocused(); // the card's arrival moved no focus
    // Approve full width at the bottom, Decline above it; tap targets of 48px or more.
    const approve = await card.getByRole("button", { name: "Approve $75/mo" }).boundingBox();
    const decline = await card.getByRole("button", { name: "Decline" }).boundingBox();
    expect(approve && decline && approve.y > decline.y && approve.height >= 48 && decline.height >= 48).toBe(true);
    // The read-back chip is its icon; its words stay for screen readers.
    await expect(card.getByLabel("Read-back progress").getByRole("listitem").first()).toHaveText("Monthly price $75.00 Read back");

    // The call tab: the chat is out of view, the card is not.
    await tabs.getByRole("button", { name: /^Call/ }).click();
    await expect(page.getByRole("region", { name: "Call", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeHidden();
    await expect(card).toBeVisible();
    await expect(page.getByRole("article", { name: "Limits m-1" })).toBeHidden();
    await shot(page, "phone-call-tab-sheet");

    // A new chat line while on Call puts a dot on Chat.
    await expect(tabs.getByRole("button", { name: "Chat" })).toHaveText("Chat");
    ws.send(ev("user.msg", "kernel", { text: "Is that the best they can do?" }));
    await expect(tabs.getByRole("button", { name: "Chat (new)" })).toBeVisible();

    await page.getByRole("button", { name: "Hide the decision" }).click();
    const bar = page.getByRole("button", { name: "Decision needed · $75/mo · Review" });
    await expect(bar).toHaveAttribute("aria-expanded", "false");
    expect((await bar.boundingBox())?.height).toBe(56);
    await expect(card).toBeHidden();
    await audit(page);
    await shot(page, "phone-sheet-folded");

    await tabs.getByRole("button", { name: "Steps" }).click();
    await expect(page.getByRole("region", { name: "Steps" })).toBeVisible();
    // One column on every tab: the steps take the full width.
    expect((await page.getByRole("region", { name: "Steps" }).boundingBox())?.width).toBeGreaterThan(300);
    await expect(page.getByRole("region", { name: "Call", exact: true })).toBeHidden();
    await bar.click();
    await expect(card).toBeVisible();
    await audit(page);
    await shot(page, "phone-steps-tab-sheet");
  });

  test("the composer is 16px, so a phone does not zoom into it", async ({ page, baseURL }) => {
    await liveWithCards(page, baseURL);
    const size = await page.getByRole("textbox", { name: "Message to the assistant" }).evaluate((el) => getComputedStyle(el).fontSize);
    expect(size).toBe("16px");
  });
});

test.describe("tablet (1024×768)", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("the status line is a strip above chat | call; Steps is a tab beside the call", async ({ page, baseURL }) => {
    await liveWithCards(page, baseURL);
    const tabs = page.getByRole("group", { name: "Show" });
    await expect(tabs.getByRole("button")).toHaveText(["Call", /^Steps/]);
    await expect(tabs.getByRole("button", { name: "Call" })).toHaveAttribute("aria-pressed", "true");
    const strip = await page.getByLabel("Status line").boundingBox();
    const chat = await page.getByRole("region", { name: "Chat", exact: true }).boundingBox();
    const call = await page.getByRole("region", { name: "Call", exact: true }).boundingBox();
    expect(strip && chat && call && strip.y < chat.y && chat.x < call.x).toBe(true);
    await expect(page.getByRole("region", { name: "Steps" })).toBeHidden();
    await shot(page, "tablet-call");
    await tabs.getByRole("button", { name: /^Steps/ }).click();
    await expect(page.getByRole("region", { name: "Steps" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Call", exact: true })).toBeHidden();
    await expect(page.getByRole("region", { name: "Chat", exact: true })).toBeVisible();
    await audit(page);
    await shot(page, "tablet-steps");
  });
});

test("reduced motion: no rise, no pulse, no ring animation", async ({ page, baseURL }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await liveWithCards(page, baseURL);
  await expect(page.getByText("Planner is listening")).toBeVisible();
  const running = await page.evaluate(() => document.getAnimations().length);
  expect(running).toBe(0);
  const named = await page.evaluate(() =>
    [...document.querySelectorAll(".pl-line, .pl-decision, .pl-pulse")].map((el) => getComputedStyle(el).animationName),
  );
  expect(named.length).toBeGreaterThan(0);
  expect(new Set(named)).toEqual(new Set(["none"]));
});

test("live regions: cards and the receipt are aria-live off; the planner line is outside the status line (#205 n5)", async ({ page, baseURL }) => {
  await liveWithCards(page, baseURL);
  const chat = page.getByRole("list", { name: "Chat transcript" });
  await expect(chat).toHaveAttribute("aria-live", "polite");
  for (const name of ["Approval ap-1", "Limits m-1"]) {
    await expect(chat.getByRole("listitem").filter({ has: page.getByRole("article", { name }) })).toHaveAttribute("aria-live", "off");
  }
  const status = page.getByLabel("Status line");
  await expect(status).toHaveAttribute("aria-live", "polite");
  await expect(page.getByText("Planner is listening")).toBeVisible();
  await expect(status).not.toContainText("Planner");
  expect(await page.getByText("Planner is listening").evaluate((el) => el.closest("[aria-live]:not([aria-live='off'])"))).toBeNull();
});
