import { expect, test, type Locator, type Page, type Response } from "@playwright/test";
import { PORTS } from "./ports";

// The S1 browser demo end to end over the real kernel (S1-SYS-32): tests/web/demo_server.py
// runs create_app with tests/support/web_demo.py's Starter, whose models are scripted
// test_fake clients; run_session, Guard, the fence and the SimRep's policy are real.
// Each scenario has its own server (ports.ts). Every event checked here is read from the
// run's own log through the real replay API.
//
// Readiness is asserted order-agnostically (S1-SYS-21's gate or main's call at the start): the
// call happens and the identity facts are public before the rep's offer. After the approved
// accept the rep confirms with an id and closes the call; the scripted Slow looks that id up in the
// simulated ledger (check_account) and finishes, and only Guard's verifier moves the case to
// VERIFIED_COMPLETE (S1-SYS-44). A stop escalates the stale case and ends the session (S1-SYS-44).
type Ev = { seq: number; event_id: string; type: string; actor: string; cause_ids: string[]; payload: Record<string, unknown> };

// The family's synthetic principal (tasks/families/x-out-of-envelope-approval.yaml).
const TASK_SAID = "Please lower my Crestline Wireless bill.";
const IDENTITY = "My name is Marcus Bell and my account ends in 5190.";
const ASK = "The company needs the account holder name and the last 4 digits."; // the scripted Slow's ask_user
const STOP = "actually, stop";
const STOPPED = "Stopped as you asked: nothing was accepted."; // the scripted Slow's tell_user on the stop
const FLOW = { timeout: 90_000 }; // wall-clock speech, holds and two read-backs
const SIM_REP = "Simulated rep; no real company was called";

async function log(page: Page, id: string): Promise<Ev[]> {
  const res = await page.request.get(`/api/replay/${id}/events`);
  expect(res.status()).toBe(200);
  return (await res.text())
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Ev);
}
const of = (events: Ev[], type: string, match: Record<string, unknown> = {}) =>
  events.filter((e) => e.type === type && Object.entries(match).every(([k, v]) => e.payload[k] === v));
const one = (events: Ev[], type: string, match: Record<string, unknown> = {}) => {
  const found = of(events, type, match);
  expect(found, `${type} ${JSON.stringify(match)}`).toHaveLength(1);
  return found[0] as Ev;
};
const causedBy = (events: Ev[], type: string, cause: Ev) => events.filter((e) => e.type === type && e.cause_ids.includes(cause.event_id));

/** Polls the run's log until `done` holds; returns that log. */
async function until(page: Page, id: string, done: (events: Ev[]) => boolean): Promise<Ev[]> {
  let events: Ev[] = [];
  await expect.poll(async () => done((events = await log(page, id))), FLOW).toBe(true);
  return events;
}

/** Every WebSocket path the page opens. */
function sockets(page: Page): string[] {
  const seen: string[] = [];
  page.on("websocket", (ws) => {
    const url = new URL(ws.url());
    seen.push(url.pathname + url.search);
  });
  return seen;
}

const shot = async (page: Page, name: string) => {
  if (process.env.PL_SHOTS) await page.screenshot({ path: `${process.env.PL_SHOTS}/${name}.png`, fullPage: true });
};

const isPost = (path: RegExp) => (r: Response) => r.request().method() === "POST" && path.test(new URL(r.url()).pathname);

/** The start page: every option is a stub labelled test_fake; Start → 201. */
async function start(page: Page, rep: "sim" | "human"): Promise<string> {
  await page.goto("/start");
  await expect(page).toHaveURL("/?start");
  await page.getByText("Advanced: models").click();
  for (const title of ["Chat voice (Fast-U)", "Phone voice (Fast-C)", "Planner (Slow)"]) {
    await expect(page.getByRole("combobox", { name: title }).locator("option")).toHaveText([/^stub · test_fake · \S+-fake · /]);
  }
  await expect(page.getByRole("radiogroup", { name: "Task" }).locator("code")).toHaveText(["x-out-of-envelope-approval@1"]);
  await yourRole(page.getByRole("region", { name: "Your role" }));
  await page.getByRole("radio", { name: rep === "sim" ? "Simulated rep" : "A person" }).check();
  const [res] = await Promise.all([page.waitForResponse(isPost(/^\/api\/cases$/)), page.getByRole("button", { name: "Start" }).click()]);
  expect(res.status()).toBe(201);
  if (rep === "human") return String(((await res.json()) as { case_id: string }).case_id);
  await expect(page).toHaveURL(/\/\?live=/);
  return new URL(page.url()).searchParams.get("live") ?? "";
}

/**
 * The principal's role card (S1-SYS-65) from the real kernel's allow-list over the family's instance: the persona, the
 * goal's numbers, the identity facts and what they would approve (the hidden limits, not the stated 65); never the
 * rep's name, ladder prices or patience.
 */
async function yourRole(role: Locator) {
  await expect(role).toContainText("Marcus Bell, a high-school teacher");
  await expect(role).toContainText("at most 65 dollars a month");
  await expect(role).toContainText("Your provider: Crestline Wireless");
  await expect(role.locator("dl").first()).toHaveText("Account holder nameMarcus BellAccount last45190");
  await expect(role.getByRole("heading", { name: "Other facts you know" })).toBeVisible();
  await expect(role.locator("dl").nth(1)).toContainText("Budget max monthly usd65"); // the limits you give when asked
  await expect(role.getByRole("heading", { name: "What you would approve" })).toBeVisible();
  await expect(role).toContainText("Monthly priceup to $72.00");
  await expect(role).toContainText("When your assistant asks for your limits, give the ones in your goal.");
  for (const hidden of ["Alex", "78.00", "69.00", "retention agent", "save-1"]) await expect(role).not.toContainText(hidden);
}

/** The rail's folded Technical details (S1-SYS-77): open it (idempotent). */
async function technical(page: Page) {
  await page.locator("details.pl-tech").evaluate((d: HTMLDetailsElement) => (d.open = true));
}

/** The live page names only test_fake models, for every role session.started lists. */
async function onlyFakes(page: Page, roles: string[]) {
  await technical(page);
  const models = page.getByRole("region", { name: "Run" }).getByRole("list", { name: "Models" }).getByRole("listitem");
  await expect(models).toHaveCount(roles.length);
  const shown = await models.allTextContents();
  expect(shown.map((t) => t.split(":")[0]).sort()).toEqual([...roles].sort());
  for (const t of shown) expect(t).toMatch(/^\w+: test_fake \w+-fake$/);
}

/** The authority strip sits behind a disclosure in Technical details: open both (idempotent). */
async function authority(page: Page) {
  await technical(page);
  await page.locator("details.authority").evaluate((d: HTMLDetailsElement) => (d.open = true));
  return page.getByRole("region", { name: "Authority" });
}

async function say(page: Page, text: string) {
  await page.getByRole("textbox", { name: "Message to the assistant" }).fill(text);
  const [res] = await Promise.all([page.waitForResponse(isPost(/\/messages$/)), page.getByRole("button", { name: "Send" }).click()]);
  expect(res.status()).toBe(200);
}

/** Start with the sim rep, state the task, answer the identity ask: up to the approval card. */
async function toCard(page: Page) {
  const id = await start(page, "sim");
  await onlyFakes(page, ["fast_user", "fast_cp", "slow", "ear", "mouth"]);
  // The world's rep is labelled on every frame: the honesty band (and each call card, below); not the chat (the user is the person here).
  await expect(page.getByRole("note", { name: "Simulated parties" })).toHaveText(SIM_REP);
  await expect(page.getByRole("region", { name: "Chat" }).locator(':scope > [aria-label="Simulated parties"]')).toHaveCount(0);
  // Every model is a test_fake: the band says so (I8), before any model would have spoken.
  await expect(page.getByText("Scripted test run · no models called")).toBeVisible();
  await say(page, TASK_SAID);
  const chat = page.getByRole("list", { name: "Chat transcript" });
  await expect(chat).toContainText(`You: ${TASK_SAID}`);
  await expect(chat).toContainText(ASK, FLOW);
  await say(page, IDENTITY);
  const card = page.getByRole("article", { name: /^Approval / });
  await expect(card.getByLabel("Approval status")).toHaveText("Waiting for your decision", FLOW);
  // Guard's read-back of the carded revision: every slot confirmed, shown on the card.
  const slots = card.getByRole("list", { name: "Read-back progress" }).getByRole("listitem");
  await expect(slots).toHaveText([
    "Monthly price $78.00 Read back",
    "Contract length 24 months Read back",
    "One-time fees None Read back",
    "Changes to your plan None Read back",
    "No expiry date Read back",
  ]);
  const events = await log(page, id);
  one(events, "chan.opened", { lane: "cp" }); // the call happens, in either readiness order
  const facts = of(events, "fact.recorded", { scope: "public", source: "shareable" });
  expect(facts.map((e) => e.payload.key).sort()).toEqual(["account.holder_name", "account.last4"]);
  const offered = of(events, "rep.policy").filter((e) => (e.payload.intent as { kind?: unknown }).kind === "offer");
  expect(Math.max(...facts.map((e) => e.seq))).toBeLessThan((offered[0] as Ev).seq); // identity before the offer
  const requested = one(events, "approval.requested");
  // The carded revision's slots, in the order the card lists them.
  const offer = of(events, "offer.recorded", { offer_ref: requested.payload.offer_ref, revision: requested.payload.revision }).at(-1);
  const terms = (offer?.payload.slots ?? []) as { field: string }[];
  expect(terms.map((t) => t.field)).toEqual(["monthly_price", "term_months", "fees_none", "changes_none", "expires"]);
  await expect(card.getByLabel("Readback")).toHaveText(String(requested.payload.readback_text));
  // The call is a card in the stream (S1-SYS-77), split where the chat interleaves: each part names the simulated rep.
  const calls = page.getByRole("group", { name: "Call with the company" });
  await expect(calls.first()).toContainText("Rep (simulated)");
  for (const part of await calls.all()) await expect(part.getByLabel("Simulated parties")).toHaveText(SIM_REP);
  await expect((await authority(page)).getByLabel("Case status")).toHaveText("status AWAITING_APPROVAL");
  await expect(page.getByLabel("Status line")).toHaveText("Waiting for you: approve or decline $78/mo for 24 months");
  return { id, card, requested };
}

test.describe("approve", () => {
  test.use({ baseURL: `http://127.0.0.1:${PORTS.approve}` });

  test("a, c) start → chat → identity → read-back → card → Approve → kernel decides → accept released and heard → verified complete; the replay shows the same chain", async ({
    page,
  }) => {
    const { id, card } = await toCard(page);
    const [res] = await Promise.all([page.waitForResponse(isPost(/\/approvals\//)), card.getByRole("button", { name: "Approve" }).click()]);
    expect([res.status(), await res.json()]).toEqual([200, { status: "posted" }]);
    await expect(card.getByLabel("Approval status")).toHaveText(/^You approved · \d{1,2}:\d{2}\s[AP]M$/, FLOW);

    const events = await until(page, id, (e) => of(e, "session.ended").length > 0);
    const posted = one(events, "approval.post");
    const decided = one(events, "approval.decided");
    expect([posted.actor, decided.actor, decided.payload.by, decided.payload.decision]).toEqual(["ui", "kernel", "ui", "granted"]);
    expect(decided.cause_ids).toEqual([posted.event_id]);
    const accept = one(events, "speak.verbatim", { kind: "accept" });
    const [released] = causedBy(events, "speak.released", accept);
    expect(released?.payload.cap_id).toBe(accept.payload.cap_id);
    const [heard] = causedBy(events, "utt.delivered", released as Ev);
    expect(heard?.payload.text_heard).toBe(accept.payload.text);
    expect(of(events, "rep.commit_heard")).toHaveLength(1);
    // The heard yes commits the case; the rep says a confirmation id (the simulated ledger's write) and closes the call.
    expect(causedBy(events, "status.changed", heard as Ev).map((e) => [e.actor, e.payload.status])).toEqual([["guard", "COMMITTED"]]);
    const write = one(events, "ledger.write");
    const conf = String(write.payload.confirmation_id);
    const [told] = of(events, "utt.final", { speaker: "partner" }).filter((e) => String(e.payload.text).includes(conf));
    expect(told?.seq).toBeLessThan(one(events, "chan.closed", { lane: "cp" }).seq);
    // Slow looks that id up, citing the rep's line; Guard records the evidence, and only its verifier's verdict completes the case.
    const looked = one(events, "slow.tool", { name: "check_account" });
    expect(looked.payload.args).toMatchObject({ confirmation_id: conf, utt_ref: told?.payload.utt_id });
    const evidence = one(events, "evidence.recorded", { confirmation_id: conf });
    expect([evidence.actor, evidence.cause_ids]).toEqual(["guard", [looked.event_id, write.event_id, (told as Ev).event_id]]);
    const finish = one(events, "slow.tool", { name: "finish" });
    expect(finish.payload.args).toMatchObject({ outcome: "completed" });
    const verdict = one(events, "completion.decided");
    expect([verdict.actor, verdict.payload.verdict, verdict.cause_ids[0]]).toEqual(["guard", "ok", finish.event_id]);
    const statuses = of(events, "status.changed").map((e) => [e.actor, e.payload.previous, e.payload.status]);
    expect(statuses.slice(-3)).toEqual([
      ["guard", "COMMIT_AUTHORIZED", "COMMITTED"],
      ["guard", "COMMITTED", "EVIDENCE_PENDING"],
      ["guard", "EVIDENCE_PENDING", "VERIFIED_COMPLETE"],
    ]);
    const ended = events.at(-1) as Ev;
    expect([ended.type, ended.actor, ended.payload.reason]).toEqual(["session.ended", "kernel", "completed"]);
    const strip = await authority(page);
    await expect(strip.getByLabel("Case status")).toHaveText("status VERIFIED_COMPLETE");
    await expect(page.getByLabel("Status line")).toHaveText("Done. Verified.");
    // The receipt (live/Receipt.tsx, outcome.ts): the verified variant, the id the rep said, Guard's verifier and your approval.
    const receipt = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
    await expect(receipt.getByRole("heading")).toHaveText("Done. Verified.");
    await expect(receipt).toContainText(`Confirmation ${conf}`);
    await expect(receipt).toContainText("Verified against the simulated company's records");
    await expect(receipt).toContainText(/Approved by you at \d{1,2}:\d{2}\s[AP]M/);
    await expect(receipt.getByLabel("Accepted terms").getByRole("listitem")).toHaveCount(5);
    // The rail's to-do (S1-SYS-79) from the same run: nothing in progress after the end, the Result row is the receipt's title,
    // and under the rows the approval, your click, Guard's clearance and the heard yes. locator("li"): a folded row's steps count too.
    const todo = page.getByRole("list", { name: "To-do" });
    await expect(todo.getByRole("listitem").filter({ hasText: /· (in progress|needs you|not started)/ })).toHaveCount(0);
    await expect(todo.getByRole("listitem").filter({ hasText: /^Result/ })).toHaveText("Result Done. Verified. · done", { useInnerText: true });
    await expect(todo.getByRole("listitem").filter({ hasText: /^Get your decision/ })).toHaveText("Get your decision Approved by your click · done", { useInnerText: true });
    const steps = page.getByRole("region", { name: "To-do" }).locator("li");
    for (const step of [
      /^Guard \d{2}:\d{2} Asked for your approval$/,
      /^You \d{2}:\d{2} Approved$/,
      /^Guard \d{2}:\d{2} Cleared to say yes \(your approval\)$/,
      /^Phone voice \d{2}:\d{2} Said yes on the call$/,
    ]) {
      await expect(steps.filter({ hasText: step })).toHaveCount(1);
    }
    // Every call part's lines (the call card splits where the chat interleaves, S1-SYS-77).
    const call = page.getByRole("list", { name: "Call transcript" }).getByRole("listitem");
    await expect(call.filter({ hasText: `Agent: ${String(accept.payload.text)}` })).toHaveCount(1);
    await expect(call.filter({ hasText: "AI disclosure · fixed wording" })).toHaveCount(1);
    // The accept's capability binds it to this card (decision.ts, conversation.ts): your grant, on the real kernel's events.
    await expect(call.filter({ hasText: "Acceptance · approved by you" })).toHaveCount(1);
    await shot(page, "demo-live-conversation");

    // c) the replay UI, from /api/bundles: the same run and the same chain.
    const listed = (await (await page.request.get("/api/bundles")).json()) as { bundles: { run_id: string }[] };
    expect(listed.bundles.map((b) => b.run_id)).toContain(id);
    // The replay opens in the conversation view; the engineer view (in place) has the lanes.
    await page.goto("/");
    await page.getByRole("list", { name: "Recorded runs" }).getByRole("link").filter({ hasText: id }).click();
    await expect(page).toHaveURL(`/?run=${id}`);
    await technical(page);
    await expect(page.getByRole("region", { name: "Run" })).toContainText(id);
    // It opens at the end: the heard yes, the approval card in its final state (no button to click), the steps.
    const timeline = page.getByRole("slider", { name: "Timeline" });
    await expect(timeline).toHaveValue((await timeline.getAttribute("max")) ?? "");
    await expect(page.getByRole("list", { name: "Call transcript" }).getByRole("listitem").filter({ hasText: `Agent: ${String(accept.payload.text)}` })).toHaveCount(1);
    const replayCard = page.getByRole("region", { name: "Chat" }).getByRole("article", { name: `Approval ${String(decided.payload.approval_id)}` });
    await expect(replayCard.getByLabel("Approval status")).toHaveText(/^You approved · \d{1,2}:\d{2}\s[AP]M$/);
    await expect(replayCard.getByRole("button", { name: "Approve $78/mo" })).toBeDisabled();
    await expect(page.getByRole("region", { name: "To-do" }).locator("li").filter({ hasText: /^You \d{2}:\d{2} Approved$/ })).toHaveCount(1);
    await expect(page.getByRole("list", { name: "To-do" }).getByRole("listitem").filter({ hasText: /^Result/ })).toHaveText("Result Done. Verified. · done", { useInnerText: true });
    const chapters = page.getByRole("list", { name: "Chapters" });
    for (const name of ["Call starts", "Offer", "Your decision"]) await expect(chapters.getByRole("button", { name, exact: true })).toBeEnabled();
    await expect(page.getByRole("region", { name: "Guard" })).toHaveCount(0);
    await shot(page, "demo-replay-conversation");
    await page.getByRole("link", { name: "Engineer view" }).click();
    await expect(page).toHaveURL(`/?run=${id}&view=engineer`);
    const guard = page.getByRole("region", { name: "Guard" });
    for (const e of [posted, decided, released as Ev]) {
      await expect(guard.getByRole("article", { name: `${e.type} #${e.seq}` })).toBeVisible();
    }
    await expect(page.getByRole("region", { name: "Rep" }).getByRole("article", { name: `utt.delivered #${(heard as Ev).seq}` })).toContainText(
      String(accept.payload.text),
    );
  });
});

test.describe("stop", () => {
  test.use({ baseURL: `http://127.0.0.1:${PORTS.stop}` });

  test("b) a stop while the card is pending raises the fence, the revoke stales the card, a post of it is refused, no accept is minted, and the case escalates", async ({
    page,
  }) => {
    const { id, card, requested } = await toCard(page);
    const strip = await authority(page);
    await say(page, STOP);
    await expect(strip.getByLabel("Fence")).toHaveText(/^fence raised \(fence-\d+\)$/);
    await expect(card.getByLabel("Fence note")).toHaveText("Paused: reading your new message before anything is accepted.");
    // FastU relays the stop as a revoke: the kernel moves the epoch and the card is stale.
    await expect(card.getByLabel("Approval status")).toHaveText("No longer valid: your instructions changed", FLOW);
    await expect(card.getByRole("button", { name: "Approve" })).toBeDisabled();
    await expect(strip.getByLabel("Epoch")).toHaveText("epoch 1");
    // Approve the stale card anyway, from the page with the user's token (the button is disabled),
    // while the case is live (Slow's step on the revoke ends it: serve then no longer knows the case):
    // serve's guard.decide pre-check answers 409 stale for the moved epoch, and nothing reaches the kernel.
    const token = (await page.context().cookies()).find((c) => c.name === "pl_csrf")?.value ?? "";
    expect(token).not.toBe("");
    const body = { decision: "granted", terms_hash: requested.payload.terms_hash, authority_epoch: requested.payload.authority_epoch };
    const path = `/api/cases/${id}/approvals/${String(requested.payload.approval_id)}`;
    const got = await page.evaluate(
      async ({ path, body, token }) => {
        const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": token }, body: JSON.stringify(body) });
        return { status: res.status, body: (await res.json()) as unknown };
      },
      { path, body, token },
    );
    expect(got).toEqual({ status: 409, body: { error: "stale", reason: "stale_epoch" } });

    const events = await until(page, id, (e) => {
      const stop = of(e, "user.msg", { text: STOP })[0];
      const fence = stop && causedBy(e, "authority.fence", stop)[0];
      return !!fence && of(e, "authority.fence", { op: "cleared", fence_id: fence.payload.fence_id }).length > 0;
    });
    const stop = one(events, "user.msg", { text: STOP });
    const [raised] = causedBy(events, "authority.fence", stop);
    expect(raised?.payload.op).toBe("raised");
    const revoke = one(events, "f2s.msg", { type: "REVOKE" });
    expect(one(events, "authority.epoch", { reason: "f2s_revoke" }).cause_ids).toEqual([revoke.event_id]);
    await expect(strip.getByLabel("Fence")).toHaveText(`fence cleared (${String(raised?.payload.fence_id)})`);
    const after = await log(page, id);
    expect([of(after, "approval.post").length, of(after, "approval.decided").length]).toEqual([0, 0]);
    // The accept is never minted, so never released: the only released line is the disclosure.
    expect(of(after, "action.authorized")).toHaveLength(0);
    expect(of(after, "speak.verbatim").map((e) => e.payload.kind)).toEqual(["disclosure"]);
    expect(of(after, "speak.released")).toHaveLength(1);
    // The stale card replans the case (S1-SYS-38); Slow's step on it escalates, which ends the session (no timeout).
    const ended = await until(page, id, (e) => of(e, "session.ended").length > 0);
    const replan = one(ended, "status.changed", { previous: "AWAITING_APPROVAL", status: "NEEDS_REPLAN" });
    expect(replan.cause_ids).toContain(one(ended, "authority.epoch", { reason: "f2s_revoke" }).event_id);
    const finish = one(ended, "slow.tool", { name: "finish" });
    expect(finish.payload.args).toMatchObject({ outcome: "escalate" });
    const escalated = one(ended, "status.changed", { previous: "NEEDS_REPLAN" });
    expect([escalated.actor, escalated.payload.status, escalated.cause_ids[0]]).toEqual(["guard", "ESCALATED", finish.event_id]);
    expect(of(ended, "status.changed").at(-1)).toBe(escalated);
    const end = ended.at(-1) as Ev;
    expect([end.type, end.actor, end.payload.reason]).toEqual(["session.ended", "kernel", "escalate"]);
    expect([of(ended, "action.authorized").length, of(ended, "completion.decided").length]).toEqual([0, 0]);
    await expect(strip.getByLabel("Case status")).toHaveText("status ESCALATED");
    await expect(page.getByLabel("Status line")).toHaveText("Ended: stopped — back to you. Not verified complete.");
    const receipt = page.getByRole("region", { name: "Chat" }).getByRole("region", { name: "Outcome" });
    await expect(receipt.getByRole("heading")).toHaveText("Ended: stopped — back to you. Not verified complete.");
    await expect(page.getByRole("list", { name: "Chat transcript" })).toContainText(STOPPED); // Slow's tell_user, voiced before the end
  });
});

test.describe("human rep", () => {
  test.use({ baseURL: `http://127.0.0.1:${PORTS.human}` });

  test("d) the rep types the offer; the rep page shows only cp speech and opens only /ws/rep", async ({ page, context }) => {
    const id = await start(page, "human");
    const started = page.getByLabel("Started");
    const [rep] = await Promise.all([context.waitForEvent("page"), started.getByRole("link", { name: "Open the rep page" }).click()]);
    const repSockets = sockets(rep);
    const repHttp: string[] = [];
    rep.on("request", (r) => repHttp.push(new URL(r.url()).pathname));
    await rep.reload(); // count every socket and request from the page's start
    await expect(rep).toHaveURL(`/?rep=${id}`);
    await started.getByRole("link", { name: "open the live page" }).click();
    await expect(page).toHaveURL(`/?live=${id}`);
    await onlyFakes(page, ["fast_user", "fast_cp", "slow"]);
    const role = page.locator("details.pl-role"); // the principal's page: its case's own card, folded
    await role.locator("summary").click();
    await yourRole(role);
    await expect(page.getByLabel("Simulated parties")).toHaveCount(0);

    // The user's own words and the case agent's private summary never reach the rep.
    const secret = "My limit is 65 dollars a month, keep that between us.";
    await say(page, secret);
    // Readiness first (S1-SYS-21): the user answers the identity ask in its own message, so the call opens ready.
    await expect(page.getByRole("list", { name: "Chat transcript" })).toContainText(ASK, FLOW);
    await say(page, IDENTITY);
    const transcript = rep.getByRole("list", { name: "Call transcript" });
    await expect(transcript.getByRole("listitem").nth(1)).toHaveText(/^Agent: Hello, this is an AI assistant/, FLOW);
    await expect(transcript).toContainText("Agent: The account holder is", FLOW); // Guard-shared facts, not the user's words
    // The live page's call card (S1-SYS-77: from chan.opened): a person, not the world.
    const calls = page.getByRole("group", { name: "Call with the company" });
    await expect(calls.first()).toBeVisible();
    for (const part of await calls.all()) await expect(part).not.toContainText("(simulated)");

    const offer = "I can offer you 70 dollars a month on a 24-month term.";
    const readback = "Here are the full terms: 70 dollars a month; a 24-month term; no fees; no other changes; no expiry.";
    for (const line of [offer, readback]) {
      await rep.getByRole("textbox", { name: "Say to the agent" }).fill(line);
      const [res] = await Promise.all([rep.waitForResponse(isPost(/\/rep$/)), rep.getByRole("button", { name: "Send" }).click()]);
      expect(res.status()).toBe(200);
      await expect(transcript).toContainText(`You: ${line}`);
      await expect(transcript.getByRole("listitem").last()).toHaveText(/^Agent: /, FLOW); // the agent answers
    }
    await expect(transcript).toContainText("Agent: Could you please read back all the terms of that offer?");
    for (const t of await transcript.getByRole("listitem").allTextContents()) expect(t).toMatch(/^(Call|Agent|You): /);

    const events = await log(page, id);
    expect(of(events, "utt.final", { speaker: "partner" }).map((e) => e.payload.text)).toEqual([offer, readback]);
    const hidden = [
      secret,
      IDENTITY,
      ...of(events, "summary.updated").map((e) => String(e.payload.text)),
      ...of(events, "utt.delivered", { lane: "user" }).map((e) => String(e.payload.text_heard)),
    ];
    expect(hidden.length).toBeGreaterThan(3);
    for (const text of hidden) await expect(rep.locator("body")).not.toContainText(text);
    expect(repSockets).toEqual([`/ws/rep/${id}?from_seq=0`]);
    const api = repHttp.filter((p) => p.startsWith("/api/") || p.startsWith("/ws/"));
    expect(api).toEqual([`/api/cases/${id}/rep`, `/api/cases/${id}/rep`]); // the two lines it sent, and nothing else
    expect(repHttp.filter((p) => p.endsWith("/card"))).toEqual([]); // never the principal's role card (S1-SYS-65)
  });
});
