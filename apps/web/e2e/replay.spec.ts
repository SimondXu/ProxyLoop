import { expect, test } from "@playwright/test";

// Generic over any bundle (PL_BUNDLE_DIR), served by the real API: the committed
// fixture by default, or an evidence/s0 bundle. No fixture-specific strings.
// PL_EXPECT_KIND (e.g. real_http): the Fast sentence's label must carry that kind.
const KINDS = process.env.PL_EXPECT_KIND ?? "real_http|recorded_replay|test_fake|baseline";

test("replays a bundle: a Fast sentence with its model label, a Slow tool, a prompt", async ({ page }) => {
  await page.goto("/");
  const run = page.getByRole("region", { name: "Run" });
  await expect(run.getByRole("list", { name: "Models" }).getByRole("listitem").first()).toBeVisible();
  const timeline = page.getByRole("slider", { name: "Timeline" });
  await timeline.fill((await timeline.getAttribute("max")) ?? "0");

  const fast = page
    .getByRole("region", { name: /^Fast-[UC]$/ })
    .getByRole("article", { name: /^fast\.sentence #/ })
    .filter({ has: page.getByText(new RegExp(`^model: (?!unknown ).+ · (${KINDS})$`)) });
  await expect(fast.first()).toBeVisible();

  const tool = page.getByRole("region", { name: "Slow" }).getByRole("article", { name: /^slow\.tool #/ });
  await expect(tool.first()).toBeVisible();

  const call = page.getByRole("article", { name: /^llm\.call #/ }).first();
  await call.getByRole("button", { name: "prompt" }).click();
  const drawer = page.getByRole("dialog", { name: "Prompt drill-down" });
  await expect(drawer.getByText(/verbatim from prompts\.jsonl/)).toBeVisible();
  await expect(drawer.getByLabel("Prompt content")).not.toBeEmpty();

  if (process.env.PL_SCREENSHOT) await page.screenshot({ path: process.env.PL_SCREENSHOT, fullPage: true });
});

// The decoys tests/web/wiring_server.py builds under its tmp root (AGENTS rule 11).
const HELD_OUT = ["heldout-split-test", "heldout-sealed-path"];

test("never lists a held-out bundle: split test, or a path through evidence/s4/test", async ({ page }) => {
  const listed = (await (await page.request.get("/api/bundles")).json()) as { bundles: { run_id: string }[] };
  const ids = listed.bundles.map((b) => b.run_id);
  expect(ids.length).toBeGreaterThan(0);
  for (const id of HELD_OUT) expect(ids).not.toContain(id);

  await page.goto("/");
  const options = page.getByRole("combobox", { name: "Run" }).locator("option");
  await expect(options).toHaveCount(ids.length);
  for (const id of HELD_OUT) await expect(options.filter({ hasText: id })).toHaveCount(0);
});

test("plays on t_ms at 4×", async ({ page }) => {
  await page.goto("/");
  const clock = page.getByLabel("Clock");
  await expect(clock).toContainText(/^0\.0 s/);
  await page.getByRole("button", { name: "4×" }).click();
  await expect(page.getByRole("button", { name: "4×" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Play" }).click();
  await expect(clock).not.toContainText(/^0\.0 s/);
  await page.getByRole("button", { name: "Pause" }).click();
});
