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
