// The receipt per variant (S1-SYS-80), rendered to static markup: the tag's words, the headline, and never a
// saving, an estimate, a mock or a yearly figure (rule 13, I11: no event carries one).
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { acceptedHeadline, headline } from "../decision";
import { receiptKind, statusView, type Outcome } from "../outcome";
import type { Ev } from "../replay";
import { termRow } from "../terms";
import { Receipt } from "./Receipt";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, cause_ids: string[] = [], stream: Ev["stream"] = "agent"): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream, cause_ids, payload, wall: "2026-09-28T14:39:00Z" };
};
const slot = (field: string, value: string, unit: string, status = "confirmed") => ({ field, value, unit, status });
const PRICE = slot("monthly_price", "7800", "usd_minor");
const TERM = slot("term_months", "24", "months", "heard");
const CARD = { approval_id: "a1", offer_ref: "offer-1", revision: 1, terms_hash: "th", readback_text: "", authority_epoch: 0, expires_ms: 90_000, binding: {} };
const SPEND = { priced_micro_usd: 12_345, unpriced_calls: 0, gpu_time_calls: 0 };

/** An offer, its card granted by you, the accept Guard released, a confirmation and the verifier's ok. */
function verifiedRun(slots = [PRICE, TERM], card = true): Ev[] {
  const offer = ev("offer.recorded", "guard", { offer_ref: "offer-1", revision: 1, terms_hash: "th", slots });
  if (!card) return [offer];
  const asked = ev("approval.requested", "guard", CARD);
  const granted = ev("approval.decided", "kernel", { approval_id: "a1", decision: "granted", by: "ui" });
  const auth = ev("action.authorized", "guard", { intent: {}, capability: { cap_id: "cap-1", terms_hash: "th", epoch: 0 } }, [granted.event_id]);
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: "cap-1" });
  const released = ev("speak.released", "kernel", { lane: "cp", cap_id: "cap-1" }, [said.event_id]);
  return [offer, asked, granted, auth, said, released];
}

/** Offer `n` at `price` minor units, its card granted by you, and its accept released, revoked (a fence) or held. */
function grantedCard(n: number, price: string, fate: "released" | "revoked" | "held"): Ev[] {
  const [ref, id, cap, th] = [`offer-${n}`, `a${n}`, `cap-${n}`, `th${n}`];
  const offer = ev("offer.recorded", "guard", { offer_ref: ref, revision: 1, terms_hash: th, slots: [slot("monthly_price", price, "usd_minor"), TERM] });
  const asked = ev("approval.requested", "guard", { ...CARD, approval_id: id, offer_ref: ref, terms_hash: th });
  const granted = ev("approval.decided", "kernel", { approval_id: id, decision: "granted", by: "ui" });
  const auth = ev("action.authorized", "guard", { intent: {}, capability: { cap_id: cap, terms_hash: th, epoch: 0 } }, [granted.event_id]);
  const said = ev("speak.verbatim", "guard", { lane: "cp", kind: "accept", text: "Yes, we accept.", cap_id: cap });
  const after =
    fate === "released"
      ? [ev("speak.released", "kernel", { lane: "cp", cap_id: cap }, [said.event_id])]
      : fate === "revoked"
        ? [ev("speak.revoked", "kernel", { lane: "cp", reason: "fence", cap_id: cap }, [said.event_id])]
        : [];
  return [offer, asked, granted, auth, said, ...after];
}

function end(events: Ev[], status: string, reason: string, verdict?: string): { events: Ev[]; outcome: Outcome } {
  const all = [
    ...events,
    ...(verdict ? [ev("evidence.recorded", "guard", { confirmation_id: "CNF-8841" }), ev("completion.decided", "guard", { verdict, reasons: [] })] : []),
    ev("status.changed", "guard", { previous: "IN_CALL", status }),
    ev("session.ended", "kernel", { reason, counts: {}, spend: SPEND }, [], "ops"),
  ];
  const outcome = statusView(all).outcome;
  if (!outcome) throw new Error("no outcome");
  return { events: all, outcome };
}

/** The card's text, tag by tag: the tag's words, the headline's and every other text node. */
function render(events: Ev[], outcome: Outcome) {
  const html = renderToStaticMarkup(createElement(Receipt, { events, outcome }));
  const plain = (s: string) => s.replace(/<[^>]+>/g, " ").replace(/&#x27;/g, "'").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
  const text = (re: RegExp) => {
    const m = html.match(re)?.[1];
    return m === undefined ? null : plain(m);
  };
  return {
    html,
    tag: text(/<span class="pl-chip [^"]*pl-outcome-tag[^"]*">([\s\S]*?)<\/span>/),
    head: text(/<h3 class="pl-outcome-head">([\s\S]*?)<\/h3>/),
    all: plain(html),
  };
}

const HONEST = /saving|saved|estimated|mock|per year|a year/i;
const OFFERS = verifiedRun([PRICE, TERM], false);

describe("the receipt per variant: tag, headline, and no saving or estimate", () => {
  it.each([
    ["verified", verifiedRun(), "VERIFIED_COMPLETE", "completed", "ok", "Done. Verified.", "Accepted: $78 a month for 24 months."],
    ["committed", [], "COMMITTED", "completed", undefined, "Receipt", "Accepted on the call. Not verified yet."],
    ["no_deal", OFFERS, "VERIFIED_NO_DEAL", "no_deal", undefined, "Receipt", "No deal. Nothing was accepted."],
    ["info_only", OFFERS, "CLOSED_NO_ACTION", "info_only", undefined, "Receipt", "Here's what they offered · nothing accepted (information only)"],
    ["abandoned", [], "ABANDONED", "abandoned", undefined, "Receipt", "The rep ended the call."],
    ["stopped", [], "IN_CALL", "timeout", undefined, "Receipt", "Stopped: the session timed out. Not completed."],
    ["endpoint", [], "IN_CALL", "llm_unavailable", undefined, "Receipt", "A model endpoint stopped responding, so the case stopped. ProxyLoop never switches to a backup model."],
    ["error", [], "IN_CALL", "error", undefined, "Receipt", "An error stopped the case. Not completed."],
    ["ended", [], "ESCALATED", "escalate", undefined, "Receipt", "Ended: stopped — back to you. Not verified complete."],
  ])("%s", (kind, before, status, reason, verdict, tag, head) => {
    const { events, outcome } = end(before as Ev[], status as string, reason as string, verdict as string | undefined);
    expect(receiptKind(outcome)).toBe(kind);
    const r = render(events, outcome);
    expect([r.tag, r.head]).toEqual([tag, head]);
    expect(r.all).not.toMatch(HONEST);
    expect(r.html).not.toMatch(HONEST); // attributes too: aria-labels, titles, classes
    expect(r.html).toContain('aria-label="Outcome"');
    expect(r.html).toContain('aria-label="Cost"');
  });

  it("keeps the verified variant's names and lines: the terms, the confirmation, the verifier, your approval", () => {
    const { events, outcome } = end(verifiedRun(), "VERIFIED_COMPLETE", "completed", "ok");
    const r = render(events, outcome);
    expect(r.html).toContain('aria-label="Accepted terms"');
    expect(r.all).toMatch(/Confirmation\s+CNF-8841/);
    expect(r.all).toContain("Verified against the simulated company's records");
    expect(r.all).toMatch(/Approved by you at \d{1,2}:\d{2}\s[AP]M/);
    expect(r.all).toContain("Read back");
    expect(r.all).toContain("Heard, not read back");
  });

  it("lists each latest offer, labelled as before, on no deal and information only", () => {
    const { events, outcome } = end(OFFERS, "CLOSED_NO_ACTION", "info_only");
    expect(render(events, outcome).html).toContain('aria-label="Offer offer-1, revision 1"');
  });

  it("keeps the unverified-commit note on a variant it fires on", () => {
    const { events, outcome } = end([ev("status.changed", "guard", { previous: "COMMIT_AUTHORIZED", status: "COMMITTED" })], "ABANDONED", "abandoned");
    expect(render(events, outcome).all).toContain("The agent had accepted on the call; this was never verified.");
  });

  it("offers Back to the call only when there was a call", () => {
    const quiet = end([], "ABANDONED", "abandoned");
    expect(render(quiet.events, quiet.outcome).all).not.toContain("Back to the call");
    const heard = ev("utt.final", "kernel", { lane: "cp", speaker: "partner", text: "Hello.", utt_id: "u1" });
    const called = end([heard], "ABANDONED", "abandoned");
    expect(render(called.events, called.outcome).all).toContain("Back to the call");
  });
});

describe("the verified headline (decision.ts acceptedHeadline, as headline() reads the rows)", () => {
  const rows = (...fields: [string, string][]) => fields.map(([field, value]) => ({ field, label: termRow(field, value)[0], value: termRow(field, value)[1], status: "confirmed" }));

  it("is built from the approved card's rows, with headline()'s price and term", () => {
    const r = rows(["monthly_price", "7800"], ["term_months", "24"], ["fees_none", "true"]);
    expect(acceptedHeadline(r)).toBe("Accepted: $78 a month for 24 months.");
    expect(headline(r)).toBe("Accept $78 a month for 24 months?"); // unchanged
  });

  it("drops the term when the card has none", () => {
    expect(acceptedHeadline(rows(["monthly_price", "7850"]))).toBe("Accepted: $78.50 a month.");
    const { events, outcome } = end(verifiedRun([PRICE]), "VERIFIED_COMPLETE", "completed", "ok");
    expect(render(events, outcome).head).toBe("Accepted: $78 a month.");
  });

  it("falls back to the receipt's title with no approved card, or no price on it; the tag then says Receipt", () => {
    expect(acceptedHeadline(rows(["term_months", "24"]))).toBeNull();
    for (const before of [verifiedRun([PRICE, TERM], false), verifiedRun([TERM])]) {
      const { events, outcome } = end(before, "VERIFIED_COMPLETE", "completed", "ok");
      const r = render(events, outcome);
      expect([r.tag, r.head]).toEqual(["Receipt", "Done. Verified."]);
    }
  });

  it.each(["revoked", "held"] as const)("uses the card whose accept was released, not a newer granted one whose accept was %s", (fate) => {
    const { events, outcome } = end([...grantedCard(1, "7800", "released"), ...grantedCard(2, "6500", fate)], "VERIFIED_COMPLETE", "completed", "ok");
    expect(render(events, outcome).head).toBe("Accepted: $78 a month for 24 months.");
  });

  it.each(["revoked", "held"] as const)("uses the newer card when its accept was released and the older one's was %s", (fate) => {
    const { events, outcome } = end([...grantedCard(1, "7800", fate), ...grantedCard(2, "6500", "released")], "VERIFIED_COMPLETE", "completed", "ok");
    expect(render(events, outcome).head).toBe("Accepted: $65 a month for 24 months.");
  });
});

describe("receipt.css", () => {
  it("draws no text of its own: no non-empty content (a CSS-only saving or badge)", () => {
    const css = readFileSync(new URL("./receipt.css", import.meta.url), "utf8");
    const values = [...css.matchAll(/(?<![-\w])content\s*:\s*([^;}]*)/g)].map((m) => m[1]?.trim());
    expect(values.filter((v) => v !== '""' && v !== "''" && v !== "none")).toEqual([]);
  });
});
