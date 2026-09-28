// axe for the e2e specs: one place that lets the page settle first. An entrance animation (pl-rise, a fade) caught
// mid-way has lower contrast than the page at rest, so every axe run waits for the finite animations; the planner's
// pulse (infinite) is left alone.
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

/** The page at rest: finite animations have run or were cancelled (their element left the layout). */
export async function settle(page: Page) {
  await page.evaluate(() =>
    Promise.all(
      document
        .getAnimations()
        .filter((a) => a.effect?.getTiming().iterations !== Infinity)
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
}

/** axe's serious and critical violations on the settled page, one line each with the nodes. */
export async function seriousViolations(page: Page): Promise<string[]> {
  await settle(page);
  const r = await new AxeBuilder({ page }).analyze();
  return r.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => `${n.target.join(" ")} ${n.failureSummary ?? ""}`).join("; ")}`);
}
