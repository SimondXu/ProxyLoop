import { expect, test } from "@playwright/test";

// Generic over any bundle (PL_BUNDLE_DIR): the committed fixture by default, an
// evidence/s0 bundle later. No fixture-specific strings.
const KINDS = "real_http|recorded_replay|test_fake|baseline";

test("replays a bundle: a Fast sentence with its model label, a Slow tool, a prompt", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Manifest" })).toBeVisible();
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
