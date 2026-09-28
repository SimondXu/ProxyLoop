import { expect, test, type Page } from "@playwright/test";

// Generic over any bundle (PL_BUNDLE_DIR), served by the real API: the committed
// fixture by default, or an evidence/s0 bundle. No fixture-specific strings.
// PL_EXPECT_KIND (e.g. real_http): the Fast sentence's label must carry that kind.
const KINDS = process.env.PL_EXPECT_KIND ?? "real_http|recorded_replay|test_fake|baseline";

// The engineer view (?view=engineer): the lanes, the model labels and the prompt drawer, unchanged.
test("replays a bundle: a Fast sentence with its model label, a Slow tool, a prompt", async ({ page }) => {
  await page.goto("/?view=engineer");
  await page.getByRole("list", { name: "Recorded runs" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\?view=engineer&run=[^&]+$/);
  const run = page.getByRole("region", { name: "Run" });
  await expect(run.getByRole("list", { name: "Models" }).getByRole("listitem").first()).toBeVisible();
  // It opens at the end: every event is shown, and the count is the engineer view's.
  const timeline = page.getByRole("slider", { name: "Timeline" });
  await expect(timeline).toHaveValue((await timeline.getAttribute("max")) ?? "");
  await expect(page.getByLabel("Events shown")).toHaveText(/^(\d+)\/\1 events$/);

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

type Ev = { type: string; actor: string; t_ms: number; payload: Record<string, unknown> };

async function openFirst(page: Page): Promise<{ id: string; events: Ev[] }> {
  await page.goto("/");
  await page.getByRole("list", { name: "Recorded runs" }).getByRole("link").first().click();
  await expect(page).toHaveURL(/\?run=[^&]+$/);
  const id = new URL(page.url()).searchParams.get("run") ?? "";
  const events = (await (await page.request.get(`/api/replay/${id}/events`)).text())
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Ev);
  return { id, events };
}

test("opens a run at its end in the conversation view: the heard lines, the receipt iff the run ended, a recording", async ({ page }) => {
  const { events } = await openFirst(page);
  const run = page.getByRole("region", { name: "Run" });
  await expect(run.getByRole("list", { name: "Models" }).getByRole("listitem").first()).toBeVisible();
  await expect(page.getByRole("region", { name: "Fast-U" })).toHaveCount(0);
  await expect(page.getByText("Replay of a recorded run", { exact: true })).toBeVisible();
  // At the end: the slider at its max, and the clock reads the same time twice.
  const timeline = page.getByRole("slider", { name: "Timeline" });
  await expect(timeline).toHaveValue((await timeline.getAttribute("max")) ?? "");
  await expect(page.getByLabel("Clock")).toHaveText(/^(\d{2}:\d{2}) \/ \1$/);
  // Read-only: no message box, the recording bar instead, and no card button can be clicked.
  const chatRegion = page.getByRole("region", { name: "Chat" });
  await expect(page.getByRole("textbox", { name: "Message to the assistant" })).toHaveCount(0);
  await expect(chatRegion.getByText(/^This is a recording: /)).toBeVisible();
  for (const b of await chatRegion.getByRole("button", { name: /^(Approve|Decline|Confirm limits|Not these)/ }).all()) await expect(b).toBeDisabled();
  // A seek must not read every line out: the replay transcripts are not aria-live.
  await expect(page.getByRole("list", { name: "Chat transcript" })).not.toHaveAttribute("aria-live", /.*/);

  const heard = (lane: string) =>
    events.filter((e) => e.type === "utt.delivered" && e.actor === "kernel" && e.payload.lane === lane).map((e) => String(e.payload.text_heard));
  const said = events.filter((e) => e.type === "user.msg" && e.actor === "kernel").map((e) => String(e.payload.text));
  const chat = page.getByRole("list", { name: "Chat transcript" }).getByRole("listitem");
  // The transcript's own items (a card's or the receipt's nested lists aside), less the Guard cards and the receipt.
  const lines = page
    .getByRole("list", { name: "Chat transcript" })
    .locator(":scope > li")
    .filter({ hasNot: page.getByRole("article") })
    .filter({ hasNot: page.getByRole("region", { name: "Outcome" }) });
  await expect(lines).toHaveCount(said.length + heard("user").length);
  for (const text of [...said, ...heard("user")]) await expect(chat.filter({ hasText: text }).first()).toBeVisible();
  const call = page.getByRole("list", { name: "Call transcript" }).getByRole("listitem");
  for (const text of heard("cp")) await expect(call.filter({ hasText: text }).first()).toBeAttached();
  const ended = events.find((e) => e.type === "session.ended" && e.actor === "kernel");
  if (ended) {
    // The receipt, in the chat as in live (S1-SYS-51), in view at open; the status line is its title.
    const outcome = chatRegion.getByRole("region", { name: "Outcome" });
    await expect(outcome).toBeInViewport();
    await expect(outcome).toContainText(`Reason: ${String(ended.payload.reason)}`);
    await expect(page.getByLabel("Status line")).toHaveText((await outcome.getByRole("heading").textContent()) ?? "");
  } else {
    await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(0);
  }
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/replay-conversation.png`, fullPage: true });

  // I11: at 00:00, before session.started's t_ms, every frame already names the simulated parties (from the whole log).
  await timeline.fill("0");
  await expect(page.getByLabel("Clock")).toHaveText(/^00:00 \/ \d{2}:\d{2}$/);
  await expect(page.getByRole("region", { name: "Outcome" })).toHaveCount(0);
  const roles = Object.keys((events.find((e) => e.type === "session.started" && e.actor === "kernel")?.payload.models ?? {}) as object);
  const labels = [
    ...(roles.includes("ear") || roles.includes("mouth") ? ["Simulated rep; no real company was called"] : []),
    ...(roles.includes("simuser") ? ["Simulated user"] : []),
  ];
  expect(labels.length, "a replayable bundle runs against the sim world").toBeGreaterThan(0);
  await expect(page.getByRole("note", { name: "Simulated parties" })).toHaveText(labels.join(" · "));
  await expect(page.getByRole("region", { name: "Call" }).getByLabel("Simulated parties")).toHaveText(labels.join(" · "));
  // The chat column is labelled only for a simulated user.
  const chatSim = chatRegion.getByLabel("Simulated parties");
  if (roles.includes("simuser")) await expect(chatSim).toHaveText("Simulated user");
  else await expect(chatSim).toHaveCount(0);
});

test("the PlaybackBar: markers and chapters from the run's own log, and a chapter seeks to its moment", async ({ page }) => {
  const { events } = await openFirst(page);
  const of = (type: string, actor: string) => events.filter((e) => e.type === type && e.actor === actor);
  const first = (found: Ev[]) => (found.length > 0 ? Math.min(...found.map((e) => e.t_ms)) : null);
  const ended = of("session.ended", "kernel");
  const offers = new Set(of("offer.recorded", "guard").map((e) => `${String(e.payload.offer_ref)}:${String(e.payload.revision)}`));
  const decisions = [...of("approval.decided", "kernel"), ...of("mandate.decided", "kernel")];
  const markers = page.getByRole("list", { name: "Markers" }).getByRole("listitem");
  for (const [name, n] of [
    ["Offer", offers.size],
    ["Approval asked", of("approval.requested", "guard").length],
    ["Decision", decisions.length],
    ["Outcome", ended.length],
  ] as const) {
    await expect(markers.filter({ hasText: new RegExp(`^${name} \\d{2}:\\d{2}$`) })).toHaveCount(n);
  }

  const chapters = page.getByRole("list", { name: "Chapters" });
  const timeline = page.getByRole("slider", { name: "Timeline" });
  const cp = events.filter((e) => e.type === "chan.opened" && e.actor === "kernel" && e.payload.lane === "cp");
  for (const [name, at] of [
    ["Call starts", first(cp)],
    ["Offer", first(of("offer.recorded", "guard"))],
    ["Your decision", first([...of("approval.requested", "guard"), ...of("mandate.proposed", "guard")])],
    ["Outcome", first(ended)],
  ] as const) {
    const chip = chapters.getByRole("button", { name, exact: true });
    if (at === null) {
      await expect(chip).toBeDisabled();
      continue;
    }
    await chip.click();
    await expect(timeline).toHaveValue(String(at));
  }
  expect(cp.length + ended.length, "the fixture has a call and an end to seek to").toBeGreaterThan(0);
});

// The decoys tests/web/wiring_server.py builds under its tmp root (AGENTS rule 11).
const HELD_OUT = ["heldout-split-test", "heldout-sealed-path"];

test("never lists a held-out bundle: split test, or a path through evidence/s4/test", async ({ page }) => {
  const listed = (await (await page.request.get("/api/bundles")).json()) as { bundles: { run_id: string; complete: boolean }[] };
  const ids = listed.bundles.map((b) => b.run_id);
  expect(ids.length).toBeGreaterThan(0);
  for (const id of HELD_OUT) expect(ids).not.toContain(id);

  await page.goto("/");
  const links = page.getByRole("list", { name: "Recorded runs" }).getByRole("link");
  await expect(links).toHaveCount(ids.length);
  for (const id of HELD_OUT) await expect(links.filter({ hasText: id })).toHaveCount(0);
  // Each row links to its run's page, with the run id and, for an incomplete bundle, the Incomplete chip.
  for (const b of listed.bundles) {
    const row = links.filter({ hasText: b.run_id });
    await expect(row).toHaveAttribute("href", `?run=${b.run_id}`);
    await expect(row.getByText("Incomplete", { exact: true })).toHaveCount(b.complete ? 0 : 1);
  }
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/replay-library.png`, fullPage: true });
});

test("plays on t_ms at 4×: Play at the end starts from 00:00", async ({ page }) => {
  await openFirst(page);
  const timeline = page.getByRole("slider", { name: "Timeline" });
  const max = (await timeline.getAttribute("max")) ?? "";
  await expect(page.getByLabel("Clock")).toHaveText(/^(\d{2}:\d{2}) \/ \1$/);
  await page.getByRole("button", { name: "4×" }).click();
  await expect(page.getByRole("button", { name: "4×" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Play" }).click();
  // It restarted from 00:00 and advances on its own, then stops at the end.
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();
  await expect(page.getByLabel("Clock")).not.toHaveText(/^00:00 \//);
  await expect(page.getByRole("button", { name: "Play" })).toBeVisible({ timeout: 20_000 });
  await expect(timeline).toHaveValue(max);
});
