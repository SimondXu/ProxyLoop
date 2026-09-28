import { expect, test } from "@playwright/test";

// Generic over any bundle (PL_BUNDLE_DIR), served by the real API: the committed
// fixture by default, or an evidence/s0 bundle. No fixture-specific strings.
// PL_EXPECT_KIND (e.g. real_http): the Fast sentence's label must carry that kind.
const KINDS = process.env.PL_EXPECT_KIND ?? "real_http|recorded_replay|test_fake|baseline";

// The engineer view (?view=engineer): the lanes, the model labels and the prompt drawer, unchanged.
test("replays a bundle: a Fast sentence with its model label, a Slow tool, a prompt", async ({ page }) => {
  await page.goto("/?view=engineer");
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

type Ev = { type: string; actor: string; payload: Record<string, unknown> };

test("opens in the conversation view: the heard lines at the end, the status line, and the banner iff the run ended", async ({ page }) => {
  await page.goto("/");
  const run = page.getByRole("region", { name: "Run" });
  await expect(run.getByRole("list", { name: "Models" }).getByRole("listitem").first()).toBeVisible();
  const id = await page.getByRole("combobox", { name: "Run" }).inputValue();
  const events = (await (await page.request.get(`/api/replay/${id}/events`)).text())
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Ev);
  await expect(page.getByRole("region", { name: "Fast-U" })).toHaveCount(0);
  await expect(page.getByLabel("Status line")).toHaveText(/^Status: /);
  // I11: at t=0, before session.started's t_ms, every frame already names the simulated parties (from the whole log).
  await expect(page.getByLabel("Clock")).toContainText(/^0\.0 s/);
  const roles = Object.keys((events.find((e) => e.type === "session.started" && e.actor === "kernel")?.payload.models ?? {}) as object);
  const labels = [
    ...(roles.includes("ear") || roles.includes("mouth") ? ["Simulated rep; no real company was called"] : []),
    ...(roles.includes("simuser") ? ["Simulated user"] : []),
  ];
  expect(labels.length, "a replayable bundle runs against the sim world").toBeGreaterThan(0);
  await expect(page.getByRole("note", { name: "Simulated parties" })).toHaveText(labels.join(" · "));
  await expect(page.getByRole("region", { name: "Call" }).getByLabel("Simulated parties")).toHaveText(labels.join(" · "));
  // The chat column is labelled only for a simulated user.
  const chatSim = page.getByRole("region", { name: "Chat" }).getByLabel("Simulated parties");
  if (roles.includes("simuser")) await expect(chatSim).toHaveText("Simulated user");
  else await expect(chatSim).toHaveCount(0);
  // A seek must not read every line out: the replay transcripts are not aria-live.
  await expect(page.getByRole("list", { name: "Chat transcript" })).not.toHaveAttribute("aria-live", /.*/);
  const timeline = page.getByRole("slider", { name: "Timeline" });
  await timeline.fill((await timeline.getAttribute("max")) ?? "0");

  const heard = (lane: string) =>
    events.filter((e) => e.type === "utt.delivered" && e.actor === "kernel" && e.payload.lane === lane).map((e) => String(e.payload.text_heard));
  const said = events.filter((e) => e.type === "user.msg" && e.actor === "kernel").map((e) => String(e.payload.text));
  const chat = page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem");
  const call = page.getByRole("list", { name: "Call transcript" }).getByRole("listitem");
  await expect(chat.filter({ hasNot: page.getByRole("region", { name: "Outcome" }) })).toHaveCount(said.length + heard("user").length);
  for (const text of [...said, ...heard("user")]) await expect(chat.filter({ hasText: text }).first()).toBeVisible();
  for (const text of heard("cp")) await expect(call.filter({ hasText: text }).first()).toBeAttached();
  const ended = events.find((e) => e.type === "session.ended" && e.actor === "kernel");
  if (ended) {
    await expect(page.getByLabel("Status line")).toHaveText(/^Session ended: /);
    // The receipt, in the chat as in live (S1-SYS-51).
    await expect(page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" })).toContainText(`Reason: ${String(ended.payload.reason)}`);
  } else {
    await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(0);
  }
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/replay-conversation.png`, fullPage: true });
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
