import { expect, test } from "@playwright/test";
import { capturePosts, CSRF, csrfCookie, events, mockSockets, RUN, shot, started } from "./liveMock";

const PRIVATE = ["walk-away floor is $60", "please keep it under $70", "offer rev 2 readback", "generated but cut"];

test("rep page: its own stream, only what the rep can hear, and it sends a rep utterance", async ({ page, baseURL }) => {
  await csrfCookie(page, baseURL);
  const { urls, connected } = await mockSockets(page);
  const posts = await capturePosts(page);
  await page.goto(`/?rep=${RUN}`);
  await expect(page.getByRole("note")).toHaveText(
    "human rep mode: not for live sessions until the server-side filter lands (S1-SYS-10)",
  );
  const ws = await connected;
  const ev = events();
  // Private and god-view events pushed on the rep stream must still not show.
  ws.send(ev("session.started", "kernel", started({ fast_cp: ["real_http", "qwen3.5-9b"] }), { stream: "ops" }));
  ws.send(ev("chan.opened", "kernel", { lane: "cp" }, { skip: 1 }));
  ws.send(ev("user.msg", "kernel", { text: PRIVATE[1] }));
  ws.send(ev("summary.updated", "guard", { scope: "private", text: PRIVATE[0] }));
  ws.send(ev("approval.requested", "guard", { approval_id: "a", readback_text: PRIVATE[2] }));
  ws.send(ev("fast.sentence", "fast.cp", { lane: "cp", text: "Hi, calling about the bill. generated but cut" }));
  ws.send(
    ev("utt.delivered", "kernel", {
      lane: "cp",
      utt_id: "u1",
      text_generated: "Hi, calling about the bill. generated but cut",
      text_heard: "Hi, calling about the bill.",
      interrupted: true,
    }),
  );
  ws.send(ev("rep.mouth", "world.mouth", { text: PRIVATE[0] }, { stream: "world" }));
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", utt_id: "p1", text: "We can do $75." }, { skip: 3 }));

  const transcript = page.getByRole("list", { name: "Call transcript" });
  await expect(transcript.getByRole("listitem")).toHaveText([
    "Call: call connected",
    "Agent: Hi, calling about the bill. [interrupted]",
    "You: We can do $75.",
  ]);
  for (const text of PRIVATE) await expect(page.locator("body")).not.toContainText(text);
  await expect(page.locator("body")).not.toContainText(/qwen|real_http|Slow|Guard/);
  await expect(page.getByLabel("Connection")).toHaveText("open"); // no raw event count

  const input = page.getByRole("textbox", { name: "Say to the agent" });
  await input.fill("Best I can do is $72.");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("list", { name: "Pending" })).toContainText("Best I can do is $72.");
  expect(posts).toEqual([{ method: "POST", path: `/api/cases/${RUN}/rep`, body: { text: "Best I can do is $72." }, csrf: CSRF }]);
  ws.send(ev("utt.final", "kernel", { lane: "cp", speaker: "partner", utt_id: "p2", text: "Best I can do is $72." }));
  await expect(transcript.getByRole("listitem").last()).toHaveText("You: Best I can do is $72.");
  await expect(page.getByRole("list", { name: "Pending" })).toHaveCount(0);
  await shot(page, "rep-page");

  expect(urls).toEqual([expect.stringMatching(new RegExp(`/ws/rep/${RUN}\\?from_seq=0$`))]);
  expect(urls.filter((u) => u.includes("/ws/live/"))).toEqual([]);
});
