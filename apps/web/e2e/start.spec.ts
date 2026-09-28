import { expect, test, type Page } from "@playwright/test";
import { csrfCookie } from "./liveMock";

// The start page against mocked /api/models and /api/cases answers (serve/start.py shapes);
// the real routes over a stub Starter are in e2e-wiring.
const OPTIONS = {
  options: [
    { id: "vllm:q", lane: "fast_user", label: "Qwen", endpoint: "vllm", model_id: "qwen3.5-9b", default: true },
    { id: "vllm:qc", lane: "fast_cp", label: "Qwen", endpoint: "vllm", model_id: "qwen3.5-9b", default: true },
    { id: "tr:g", lane: "slow", label: "Gemini", endpoint: "teamrouter", model_id: "gemini-3.8-flash", default: true },
  ],
  tasks: ["cp-direct-discount"],
};

async function answer(page: Page, models: { status: number; json: unknown }, cases: { status: number; json: unknown }) {
  const posts: unknown[] = [];
  await page.route("**/api/models", (route) => route.fulfill(models));
  await page.route("**/api/cases", async (route) => {
    posts.push(route.request().postDataJSON());
    await new Promise((r) => setTimeout(r, 200)); // a slow kernel: a second click lands while the first is in flight
    await route.fulfill(cases);
  });
  return posts;
}

test("a broken options answer (500 options) and a missing operator cookie are shown", async ({ page }) => {
  await answer(page, { status: 500, json: { error: "options", reason: "lane 'slow' does not have exactly one default" } }, { status: 201, json: {} });
  await page.goto("/?start");
  await expect(page.getByRole("alert")).toHaveText("Options unavailable: 500 options: lane 'slow' does not have exactly one default");
  await expect(page.getByRole("note").getByRole("link", { name: "open /start" })).toHaveAttribute("href", "/start");
  await expect(page.getByRole("button", { name: "Start" })).toHaveCount(0);
});

for (const [status, json, shown] of [
  [503, { error: "unavailable" }, /^Not started: 503 unavailable \(/],
  [422, { error: "invalid body" }, "Not started: 422 invalid body (the server refused the form)"],
  [400, { error: "start", reason: "not_live" }, "Not started: 400 start: not_live (a chosen model cannot run live)"],
] as const) {
  test(`a ${status} is shown, a double click posts once, and nothing retries`, async ({ page, baseURL }) => {
    await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
    const posts = await answer(page, { status: 200, json: OPTIONS }, { status, json });
    await page.goto("/?start");
    await expect(page.getByRole("note")).toHaveCount(0);
    await page.getByRole("button", { name: "Start" }).dblclick();
    await expect(page.getByRole("alert")).toHaveText(shown);
    await page.waitForTimeout(300);
    expect(posts).toEqual([{ task_ref: "cp-direct-discount", models: { fast_user: "vllm:q", fast_cp: "vllm:qc", slow: "tr:g" }, rep: "sim" }]);
    await expect(page.getByRole("button", { name: "Start" })).toBeEnabled(); // a new start is the operator's click
  });
}

test("no answer, or a 201 without a case_id, may have started a session: Start stays disabled (no second paid session)", async ({
  page,
  baseURL,
}) => {
  await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
  await page.route("**/api/models", (route) => route.fulfill({ status: 200, json: OPTIONS }));
  let posts = 0;
  let abort = true;
  await page.route("**/api/cases", (route) => {
    posts += 1;
    return abort ? route.abort("connectionreset") : route.fulfill({ status: 201, json: {} });
  });
  for (const shown of [/^Not started: no response: .*The session may have started: open the live page or reload$/, /^Not started: no case_id in the answer\. The session may have started/]) {
    const before = posts;
    await page.goto("/?start");
    await page.getByRole("button", { name: "Start" }).click();
    await expect(page.getByRole("alert")).toHaveText(shown);
    await expect(page.getByRole("button", { name: "Start" })).toBeDisabled();
    await page.getByRole("button", { name: "Start" }).click({ force: true });
    await page.waitForTimeout(300);
    expect(posts - before).toBe(1);
    abort = false;
  }
});

test("a malformed operator cookie is not a missing one: no 'open /start' note, and the Start says why without posting", async ({
  page,
  baseURL,
}) => {
  await csrfCookie(page, baseURL, "pl_op_csrf", "%E0%A4%A"); // #173 N-4: decodeURIComponent throws
  const posts = await answer(page, { status: 200, json: OPTIONS }, { status: 201, json: { case_id: "never" } });
  await page.goto("/?start");
  await expect(page.getByRole("button", { name: "Start" })).toBeEnabled();
  await expect(page.getByRole("note")).toHaveCount(0);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByRole("alert")).toHaveText("Not started: bad pl_op_csrf cookie");
  expect(posts).toEqual([]);
});

// S1-SYS-65: the chosen task's role card, from GET /api/tasks/card (a synthetic card).
test("the start page shows the chosen task's role card: what you know, and what you would approve (not a target)", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
  await answer(page, { status: 200, json: { ...OPTIONS, tasks: ["cp-direct-discount", "x-user-mind-change"] } }, { status: 201, json: {} });
  const asked: string[] = [];
  await page.route("**/api/tasks/card?*", (route) => {
    const ref = new URL(route.request().url()).searchParams.get("ref") ?? "";
    asked.push(ref);
    const stop = ref === "x-user-mind-change" ? { trigger: "after_card", text_hint: "Tell the assistant to stop.", change: null } : null;
    return route.fulfill({
      status: 200,
      json: {
        company: "Example Mobile",
        persona: `The principal of ${ref}.`,
        goal: "Pay less every month.",
        facts: [{ key: "account.last4", value: "1234", identity: true, shareable: true }],
        approval: stop ? { max_monthly_price_usd: "64.00", max_term_months: 12, max_one_time_fees_usd: "0" } : null,
        stop,
      },
    });
  });
  await page.goto("/?start");
  const role = page.getByRole("region", { name: "Your role" });
  await expect(role).toContainText("The principal of cp-direct-discount.");
  await expect(role).toContainText("Nothing: this task only gathers information");
  await page.getByRole("radio", { name: /X user mind change/ }).check();
  await expect(role).toContainText("The principal of x-user-mind-change.");
  await expect(role.getByRole("heading", { name: "What you would approve" })).toBeVisible();
  await expect(role).toContainText("This is not a target to aim for.");
  await expect(role).toContainText("Once you have seen an approval card: Tell the assistant to stop.");
  expect(asked).toEqual(["cp-direct-discount", "x-user-mind-change"]);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

// S1-SYS-81: the v4 landing over the same data. The cards say only what /api/models gives: the task's name (from its
// ref), the ref and "Runs in this demo" (every task it lists runs here); no company, category or saving.
const THREE = ["cp-direct-discount", "x-user-mind-change", "x-out-of-envelope-approval@1"];
const NAMES = ["Cp direct discount", "X user mind change", "X out of envelope approval"];

test("the Task radiogroup keeps its name, arrow keys and card names; each card shows only its name, ref and tag", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
  await answer(page, { status: 200, json: { ...OPTIONS, tasks: THREE } }, { status: 201, json: {} });
  await page.goto("/?start");
  const group = page.getByRole("radiogroup", { name: "Task" });
  const radios = group.getByRole("radio");
  await expect(radios).toHaveCount(3);
  for (const [i, ref] of THREE.entries()) {
    const radio = radios.nth(i);
    await expect(radio).toHaveAccessibleName(`${NAMES[i]} ${ref}`); // the name as before; the tag is its description
    await expect(radio).toHaveAccessibleDescription("Runs in this demo");
    const card = page.locator(".pl-task").nth(i);
    await expect(card.getByText("Runs in this demo", { exact: true })).toBeVisible();
    // the rendered text is exactly {taskName(ref), ref, the tag}: nothing the API did not return
    const pieces = await card.evaluate((el) => {
      const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      const out: string[] = [];
      for (let n = walk.nextNode(); n; n = walk.nextNode()) if (n.textContent?.trim()) out.push(n.textContent.trim());
      return out.sort();
    });
    expect(pieces).toEqual([NAMES[i], ref, "Runs in this demo"].sort());
  }
  await expect(radios.nth(0)).toBeChecked();
  await radios.nth(0).focus();
  await page.keyboard.press("ArrowDown");
  await expect(radios.nth(1)).toBeChecked();
  await expect(radios.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(radios.nth(0)).toBeChecked();
  await page.keyboard.press("ArrowLeft"); // wraps
  await expect(radios.nth(2)).toBeChecked();
  // not a hue alone: the checked card's tile swaps the phone for a check mark (and the ring doubles), visible in both themes
  const tile = (i: number) =>
    page.locator(".pl-task-tile").nth(i).evaluate((el) => {
      const after = getComputedStyle(el, "::after");
      return {
        check: after.content,
        phone: el.querySelector("svg") ? getComputedStyle(el.querySelector("svg") as Element).display : "gone",
        stroke: parseFloat(after.borderRightWidth),
        inked: after.borderRightColor !== getComputedStyle(el).backgroundColor,
      };
    });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await expect(page.locator("html")).toHaveAttribute("data-theme", scheme);
    const on = await tile(2);
    expect(on).toMatchObject({ check: '""', phone: "none", inked: true });
    expect(on.stroke).toBeGreaterThan(0);
    expect(await tile(0)).toMatchObject({ check: "none", phone: "block" });
  }
});

test("the greeting follows the local clock and names nobody", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
  await answer(page, { status: 200, json: OPTIONS }, { status: 201, json: {} });
  for (const [time, word] of [
    ["2026-09-28T04:59:00", "evening"],
    ["2026-09-28T09:30:00", "morning"],
    ["2026-09-28T12:00:00", "afternoon"],
  ] as const) {
    await page.clock.setFixedTime(new Date(time)); // local time, as the page reads it
    await page.goto("/?start");
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toHaveText(`Good ${word}: start a new case`); // the last words are sr-only: the page's purpose (WCAG 2.4.6)
    await expect(h1).toHaveAccessibleName(/new case/);
  }
});

test.describe("at 390 wide", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("the cards stack, nothing scrolls sideways, and Start stays reachable", async ({ page, baseURL }) => {
    await csrfCookie(page, baseURL, "pl_op_csrf", "op-token");
    await answer(page, { status: 200, json: { ...OPTIONS, tasks: THREE } }, { status: 201, json: {} });
    await page.goto("/?start");
    await expect(page.getByRole("radiogroup", { name: "Task" }).getByRole("radio")).toHaveCount(3);
    const boxes = await page.locator(".pl-task").evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON() as DOMRect));
    expect(boxes).toHaveLength(3);
    expect(new Set(boxes.map((b) => Math.round(b.x))).size).toBe(1);
    for (const [i, b] of boxes.slice(1).entries()) expect(b.y).toBeGreaterThanOrEqual((boxes[i]?.bottom ?? Infinity) - 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    const go = page.getByRole("button", { name: "Start" });
    await go.scrollIntoViewIfNeeded();
    await expect(go).toBeInViewport();
    await expect(go).toBeEnabled();
  });
});
