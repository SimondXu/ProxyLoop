import { expect, test, type Page } from "@playwright/test";
import { seriousViolations } from "./axe";
import { capturePosts, CSRF, csrfCookie, events, mockSockets, REP_CSRF, repFrames, RUN, shot, started } from "./liveMock";

// UI-8 (redesign §2.4, §3.6, §7 risk 10): axe on Start, Live (an open approval
// card and a limits card) and Rep, at desktop and phone sizes, 0 serious or
// critical; reduced motion; the phone's stream and decision sheet. S1-SYS-76: every
// axe check runs in the light and the dark theme (the emulated OS scheme, no stored choice).
const THEMES = ["light", "dark"] as const;
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
/** A synthetic GET /api/tasks/card answer (S1-SYS-65 shape) for the start page's "Your role". */
const ROLE_CARD = {
  company: "Example Mobile",
  persona: "A synthetic account holder.",
  goal: "Pay less every month.",
  facts: [{ key: "account.last4", value: "1234", identity: true, shareable: true }],
  approval: { max_monthly_price_usd: "64.00", max_term_months: 12, max_one_time_fees_usd: "0" },
  stop: null,
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

/** axe on the page at rest (./axe.ts waits for the entrance animations). */
async function audit(page: Page) {
  // No stored choice: the page's theme is the emulated OS scheme's.
  const scheme = await page.evaluate(() => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
  expect(await seriousViolations(page)).toEqual([]);
}

/** WCAG contrast of an element's text on its own background (both opaque rgb). */
function contrast(el: Element): number {
  const s = getComputedStyle(el);
  const lum = (c: string) => {
    const [r, g, b] = (c.match(/\d+(\.\d+)?/g) ?? []).slice(0, 3).map((v) => {
      const x = Number(v) / 255;
      return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (b ?? 0);
  };
  const [hi, lo] = [lum(s.color), lum(s.backgroundColor)].sort((a, b) => b - a);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** In the viewport and on top at its centre: nothing (the decision sheet) covers it. */
function uncovered(el: Element): boolean {
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return r.top >= 0 && r.bottom <= innerHeight && hit !== null && el.contains(hit);
}

/** Five term rows for the carded offer (S1-SYS-77: Approve stays whole in the sheet with 3 and 5 rows). */
const FIVE = [
  ...OFFER.slots,
  { field: "fees_none", value: "true", unit: "bool", status: "confirmed" },
  { field: "changes_none", value: "true", unit: "bool", status: "heard" },
  { field: "expires", value: "none", unit: "iso", status: "confirmed" },
];

/** A live page with the user's message, a call line, a limits card and an open approval card for $75/mo (`slots`: its terms). */
async function liveWithCards(page: Page, baseURL: string | undefined, refs = REAL, slots = OFFER.slots) {
  await csrfCookie(page, baseURL, "pl_csrf", CSRF);
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  const ev = events();
  ws.send(ev("session.started", "kernel", started(refs), { stream: "ops" }));
  ws.send(ev("user.msg", "kernel", { text: "Please lower my internet bill." }));
  ws.send(ev("status.changed", "guard", { previous: "INTAKE", status: "IN_CALL" }));
  ws.send(ev("chan.opened", "kernel", { lane: "cp" }));
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", text: "We can do $75 a month for 12 months." }));
  ws.send(ev("mandate.proposed", "guard", MANDATE));
  ws.send(ev("offer.recorded", "guard", { ...OFFER, slots }));
  ws.send(ev("approval.requested", "guard", CARD));
  await expect(page.getByRole("article", { name: "Approval ap-1" }).getByLabel("Approval status")).toHaveText("Waiting for your decision");
  await expect(page.getByRole("article", { name: "Limits m-1" }).getByLabel("Limits status")).toHaveText("Waiting for your confirmation");
  return { ws, ev };
}

/**
 * S1-SYS-78: the approval card beside confirmed limits (the limit column, the price bar, the lists as text rows),
 * the rep on hold, and the granted limits card; `slots`: the card's terms.
 */
async function liveBesideLimits(page: Page, baseURL: string | undefined, slots = FIVE) {
  await csrfCookie(page, baseURL, "pl_csrf", CSRF);
  const { connected } = await mockSockets(page);
  await page.goto(`/?live=${RUN}`);
  const ws = await connected;
  const ev = events();
  ws.send(ev("session.started", "kernel", started(REAL), { stream: "ops" }));
  ws.send(ev("user.msg", "kernel", { text: "Please lower my internet bill." }));
  ws.send(ev("mandate.proposed", "guard", { ...MANDATE, max_monthly_price_minor: 6500, max_term_months: null, required_features: ["hotspot"], forbidden_changes: ["speed_tier"] }));
  ws.send(ev("mandate.decided", "kernel", { mandate_id: "m-1", mandate_hash: MANDATE.mandate_hash, decision: "granted", by: "ui" }));
  ws.send(ev("authority.epoch", "kernel", { new: 1, reason: "mandate_decided" }));
  ws.send(ev("chan.opened", "kernel", { lane: "cp" }));
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", text: "We can do $75 a month for 12 months." }));
  ws.send(ev("chan.hold", "fast.cp", { lane: "cp", reason: "decision" }));
  ws.send(ev("offer.recorded", "guard", { ...OFFER, slots }));
  ws.send(ev("approval.requested", "guard", { ...CARD, authority_epoch: 1, binding: { ...CARD.binding, authority_epoch: 1 } }));
  const card = page.getByRole("article", { name: "Approval ap-1" });
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision");
  await expect(card.getByText(/^The rep is holding · \d+:\d{2}$/)).toBeVisible();
  await expect(page.getByRole("article", { name: "Limits m-1" }).getByLabel("Limits status")).toHaveText(/^Confirmed by you/);
  return card;
}

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    test.use({ colorScheme: theme });

    for (const size of SIZES) {
      test.describe(`axe at ${size.width}×${size.height}`, () => {
        test.use({ viewport: { width: size.width, height: size.height } });

        test("start page, then another task chosen with its role card open", async ({ page, baseURL }) => {
          await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
          await page.route("**/api/models", (route) => route.fulfill({ status: 200, json: { ...OPTIONS, tasks: [...OPTIONS.tasks, "x-user-mind-change"] } }));
          await page.route("**/api/tasks/card?*", (route) => route.fulfill({ status: 200, json: ROLE_CARD }));
          await page.goto("/?start");
          await expect(page.getByRole("button", { name: /Start/ })).toBeEnabled();
          await audit(page);
          await page.getByRole("radio", { name: /X user mind change/ }).check(); // S1-SYS-81: the selected card's ring and check
          await expect(page.getByRole("region", { name: "Your role" })).toContainText("Pay less every month.");
          await audit(page);
          await shot(page, `a11y-start-${size.name}-${theme}`);
        });

        test("live page with an open approval card and a limits card", async ({ page, baseURL }) => {
          await liveWithCards(page, baseURL);
          await audit(page);
          await shot(page, `a11y-live-${size.name}-${theme}`);
        });

        test("live page with an approval card beside confirmed limits, the rep on hold (S1-SYS-78)", async ({ page, baseURL }) => {
          const card = await liveBesideLimits(page, baseURL);
          await expect(card.locator(".pl-lbar-l")).toHaveText(["Your limit $65", "This offer $75"]);
          await audit(page);
          await shot(page, `a11y-live-limits-${size.name}-${theme}`);
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
          await shot(page, `a11y-rep-${size.name}-${theme}`);
        });
      });
    }

    test.describe("phone (390×844)", () => {
      test.use({ viewport: { width: 390, height: 844 } });

      test("the decision is a non-modal sheet over the stream, folds to a bar, never takes focus; the composer and Task details stay reachable", async ({
        page,
        baseURL,
      }) => {
        const { ws, ev } = await liveWithCards(page, baseURL);
        const card = page.getByRole("article", { name: "Approval ap-1" });
        // One stream, no tabs (S1-SYS-77): the chat lines, the call card and the Guard cards in one list.
        await expect(page.getByRole("group", { name: "Show" })).toHaveCount(0);
        await expect(page.getByRole("group", { name: "Call with the company" }).getByRole("listitem")).toHaveText([
          "Call: call connected",
          "Rep (simulated): We can do $75 a month for 12 months.",
        ]);
        await expect(page.locator("body")).toBeFocused(); // the card's arrival moved no focus
        // Approve full width at the bottom, Decline above it; tap targets of 48px or more. Measured once the card's
        // pl-rise entry (translateY, 320ms) has finished: mid-transform a 48px button measures 47.9999px.
        await card.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
        const approve = await card.getByRole("button", { name: "Approve $75/mo" }).boundingBox();
        const decline = await card.getByRole("button", { name: "Decline" }).boundingBox();
        expect(approve && decline && approve.y > decline.y && approve.height >= 48 && decline.height >= 48).toBe(true);
        // The read-back chip is its icon; its words stay for screen readers.
        await expect(card.getByLabel("Read-back progress").getByRole("listitem").first()).toHaveText("Monthly price $75.00 Read back");
        // The band's authority line is hidden on a phone; the sheet carries it, where the click is (I6).
        const promise = page.getByText("Only your clicks can authorize a deal", { exact: true }).filter({ visible: true });
        await expect(promise).toHaveCount(1);
        // No sideways scroll; the composer, Send and the Task details button are in view and uncovered by the open sheet.
        expect(await page.evaluate(() => (document.scrollingElement?.scrollWidth ?? Infinity) <= innerWidth)).toBe(true);
        const details = page.getByRole("button", { name: "Task details" });
        for (const el of [page.getByRole("textbox", { name: "Message to the assistant" }), page.getByRole("button", { name: "Send" }), details]) {
          expect(await el.evaluate(uncovered)).toBe(true);
        }
        await shot(page, `phone-sheet-open-${theme}`);

        // A new chat line joins the stream under the open sheet (was: a dot on the Chat tab).
        ws.send(ev("user.msg", "kernel", { text: "Is that the best they can do?" }));
        await expect(page.getByRole("list", { name: "Chat transcript" })).toContainText("You: Is that the best they can do?");

        await page.getByRole("button", { name: "Hide the decision" }).click();
        const bar = page.getByRole("button", { name: "Decision needed · $75/mo · Review" });
        await expect(bar).toHaveAttribute("aria-expanded", "false");
        expect((await bar.boundingBox())?.height).toBe(56);
        await expect(card).toBeHidden();
        await expect(bar.getByText("Only your click authorizes", { exact: true })).toBeVisible();
        await expect(promise).toHaveCount(0);
        await audit(page);
        await shot(page, `phone-sheet-folded-${theme}`);

        // Task details opens a drawer from the case header with the steps at full width (was: the Steps tab).
        await details.click();
        const steps = page.getByRole("region", { name: "Steps" });
        await expect(steps).toBeVisible();
        expect((await steps.boundingBox())?.width).toBeGreaterThan(300);
        await expect(page.getByRole("button", { name: "Close" })).toBeFocused();
        // The drawer opens under the sticky band: the sim label stays in view on every frame (I8, I11).
        expect(await page.getByRole("note", { name: "Simulated parties" }).evaluate(uncovered)).toBe(true);
        await audit(page);
        await shot(page, `phone-details-${theme}`);
        await page.keyboard.press("Escape");
        await expect(steps).toBeHidden();
        await expect(details).toBeFocused();
        await bar.click();
        await expect(card).toBeVisible();
        await audit(page);
      });

      test("a simulated principal's sheet and folded bar never say only your click authorizes (I6)", async ({ page, baseURL }) => {
        await liveWithCards(page, baseURL, { ...REAL, simuser: ["test_fake", "sim-user"] });
        await expect(page.getByRole("article", { name: "Approval ap-1" })).toBeVisible();
        await expect(page.getByText("Only your clicks can authorize a deal", { exact: true })).toHaveCount(0);
        await page.getByRole("button", { name: "Hide the decision" }).click();
        const bar = page.getByRole("button", { name: "Decision needed · $75/mo · Review", exact: true });
        expect((await bar.boundingBox())?.height).toBe(56);
        await expect(page.getByText("Only your click authorizes", { exact: true })).toHaveCount(0);
        await audit(page);
      });

      test("the Task details button under the pointer keeps readable colours (#216, was the pressed tab)", async ({ page, baseURL }) => {
        await liveWithCards(page, baseURL);
        const details = page.getByRole("button", { name: "Task details" });
        await details.click(); // the drawer opens; the pointer stays where the button was
        await expect(details).toHaveAttribute("aria-expanded", "true");
        await audit(page);
        await page.keyboard.press("Escape");
        await page.mouse.move(0, 0);
        await details.hover();
        await audit(page);
        expect(await details.evaluate(contrast)).toBeGreaterThanOrEqual(4.5);
      });

      test("a card decided in the sheet leaves the sheet and stays in the stream with its status (#216, was the Call tab)", async ({ page, baseURL }) => {
        await capturePosts(page);
        await liveWithCards(page, baseURL);
        await page.getByRole("article", { name: "Approval ap-1" }).getByRole("button", { name: "Approve $75/mo" }).click();
        await expect(page.getByRole("button", { name: "Hide the decision" })).toHaveCount(0);
        const card = page.getByRole("list", { name: "Chat transcript" }).getByRole("article", { name: "Approval ap-1" });
        await expect(card.getByLabel("Approval status")).toHaveText("Sent. Waiting for Guard to record it");
        await card.scrollIntoViewIfNeeded();
        await expect(card).toBeInViewport();
      });

      const SHORT = [
        [667, 375],
        [740, 360],
      ] as const;
      for (const [rows, size] of [...[2, 3, 5].map((n) => [n, null] as const), ...[3, 5].flatMap((n) => SHORT.map((s) => [n, s] as const))]) {
        const at = size ? ` at ${size[0]}×${size[1]} (a short phone: the page scrolls)` : "";
        test(`the open sheet shows the whole Approve button with ${rows} term rows${at} (S1-SYS-76 review)`, async ({ page, baseURL }) => {
          if (size) await page.setViewportSize({ width: size[0], height: size[1] });
          await liveWithCards(page, baseURL, REAL, FIVE.slice(0, rows));
          const card = page.getByRole("article", { name: "Approval ap-1" });
          await expect(card.getByLabel("Read-back progress").getByRole("listitem")).toHaveCount(rows);
          await card.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
          // The decision row is the sheet's sticky footer: whole, while the terms scroll above it.
          await expect(card.getByRole("button", { name: "Approve $75/mo" })).toBeInViewport({ ratio: 1 });
          await expect(card.getByRole("button", { name: "Decline" })).toBeInViewport({ ratio: 1 });
          expect(await card.getByRole("button", { name: "Approve $75/mo" }).evaluate(uncovered)).toBe(true);
        });
      }

      for (const [rows, size] of [...[2, 3, 5].map((n) => [n, null] as const), [5, [360, 740]] as const]) {
        const at = size ? ` at ${size[0]}×${size[1]}` : "";
        test(`beside confirmed limits, the open sheet shows the whole Approve and Decline with ${rows} term rows${at} (S1-SYS-78)`, async ({
          page,
          baseURL,
        }) => {
          if (size) await page.setViewportSize({ width: size[0], height: size[1] });
          const card = await liveBesideLimits(page, baseURL, FIVE.slice(0, rows));
          await expect(card.getByLabel("Read-back progress").getByRole("listitem")).toHaveCount(rows);
          await card.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
          for (const name of ["Approve $75/mo", "Decline"]) {
            await expect(card.getByRole("button", { name })).toBeInViewport({ ratio: 1 });
            expect(await card.getByRole("button", { name }).evaluate(uncovered)).toBe(true);
          }
          expect(await page.evaluate(() => (document.scrollingElement?.scrollWidth ?? Infinity) <= innerWidth)).toBe(true);
          // The sheet carries the human principal's promise once; the card's own line is not shown twice.
          await expect(page.getByText(/^Only your clicks? can authorize a deal$/).filter({ visible: true })).toHaveCount(1);
        });
      }

      test("at 360×740 the open sheet leaves the composer and Task details reachable, and Approve whole", async ({ page, baseURL }) => {
        await page.setViewportSize({ width: 360, height: 740 });
        await liveWithCards(page, baseURL, REAL, FIVE);
        const card = page.getByRole("article", { name: "Approval ap-1" });
        await card.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
        expect(await page.evaluate(() => (document.scrollingElement?.scrollWidth ?? Infinity) <= innerWidth)).toBe(true);
        const approve = card.getByRole("button", { name: "Approve $75/mo" });
        for (const el of [page.getByRole("textbox", { name: "Message to the assistant" }), page.getByRole("button", { name: "Task details" }), approve]) {
          expect(await el.evaluate(uncovered)).toBe(true);
        }
        await expect(approve).toBeInViewport({ ratio: 1 });
        await shot(page, `phone-360-sheet-${theme}`);
        // The Task details drawer opens under the band: the sim label is not covered (I8, I11).
        await page.getByRole("button", { name: "Task details" }).click();
        await expect(page.getByRole("region", { name: "Steps" })).toBeVisible();
        expect(await page.getByRole("note", { name: "Simulated parties" }).evaluate(uncovered)).toBe(true);
        await shot(page, `phone-360-details-${theme}`);
      });

      test("the composer is 16px, so a phone does not zoom into it", async ({ page, baseURL }) => {
        await liveWithCards(page, baseURL);
        const size = await page.getByRole("textbox", { name: "Message to the assistant" }).evaluate((el) => getComputedStyle(el).fontSize);
        expect(size).toBe("16px");
      });
    });

    test.describe("tablet (1024×768)", () => {
      test.use({ viewport: { width: 1024, height: 768 } });

      test("one stream, the card inline; the rail is a drawer behind the Task details button", async ({ page, baseURL }) => {
        const { ws, ev } = await liveWithCards(page, baseURL);
        const details = page.getByRole("button", { name: "Task details" });
        await expect(details).toHaveAttribute("aria-expanded", "false");
        await expect(page.getByRole("region", { name: "Steps" })).toBeHidden();
        // Closed, the drawer keeps its status line in the accessibility tree (visually hidden), so changes are announced.
        const status = page.getByRole("status", { name: "Status line" });
        await expect(status).toHaveAttribute("aria-live", "polite");
        ws.send(ev("session.ended", "kernel", { reason: "abandoned", counts: {} }, { stream: "ops" }));
        await expect(status).toHaveText("The rep ended the call.");
        await expect(page.getByRole("button", { name: "Hide the decision" })).toBeHidden(); // no sheet from 768px
        await expect(page.getByRole("article", { name: "Approval ap-1" })).toBeVisible();
        expect((await page.getByRole("region", { name: "Chat", exact: true }).boundingBox())?.width).toBeLessThanOrEqual(760);
        await shot(page, `tablet-stream-${theme}`);
        await details.click();
        await expect(page.getByRole("region", { name: "Steps" })).toBeVisible();
        await expect(page.getByLabel("Status line")).toBeVisible();
        await audit(page);
        await shot(page, `tablet-details-${theme}`);
        // Escape closes it wherever the focus is, here in the composer outside the drawer.
        await page.getByRole("textbox", { name: "Message to the assistant" }).focus();
        await page.keyboard.press("Escape");
        await expect(page.getByRole("region", { name: "Steps" })).toBeHidden();
        await expect(details).toHaveAttribute("aria-expanded", "false");
      });
    });

    test.describe("landscape phone (844×390)", () => {
      test.use({ viewport: { width: 844, height: 390 } });

      test("a short viewport scrolls the page instead of squeezing the stream", async ({ page, baseURL }) => {
        await liveWithCards(page, baseURL);
        expect((await page.getByRole("list", { name: "Chat transcript" }).boundingBox())?.height).toBeGreaterThanOrEqual(200);
        const card = page.getByRole("article", { name: "Approval ap-1" });
        await card.getByRole("button", { name: "Approve $75/mo" }).scrollIntoViewIfNeeded();
        await expect(card.getByRole("button", { name: "Approve $75/mo" })).toBeInViewport({ ratio: 1 });
        await expect(card.getByRole("heading")).toBeAttached();
        await audit(page);
        await shot(page, `landscape-phone-${theme}`);
      });
    });
  });
}

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
