import { describe, expect, it } from "vitest";
import { paths } from "./liveApi";
import { approvalRows, factLabel, factRows, parseRoleCard, stopWhen, type RoleCard } from "./role";

// A synthetic card in serve.cases RoleCard's shape (not a task file's values).
const CARD: RoleCard = {
  company: "Example Mobile",
  persona: "Sam Doe, a teacher.",
  goal: "Pay at most 60 dollars a month.",
  facts: [
    { key: "account.holder_name", value: "Sam Doe", identity: true, shareable: true },
    { key: "competitor.price_usd", value: "55", identity: false, shareable: true },
    { key: "budget.max_monthly_usd", value: "60", identity: false, shareable: false },
  ],
  approval: { max_monthly_price_usd: "64.00", max_term_months: 12, max_one_time_fees_usd: "0" },
  stop: { trigger: "after_card", text_hint: "Say stop.", change: null },
};

describe("the principal's role card (GET /api/tasks/card, /api/cases/{case}/card)", () => {
  it("keeps a well-formed card as sent, with or without an approval or a stop", () => {
    expect(parseRoleCard(CARD)).toEqual(CARD);
    const info = { ...CARD, approval: null, stop: null };
    expect(parseRoleCard(info)).toEqual(info);
    const unbounded = { ...CARD, approval: { max_monthly_price_usd: null, max_term_months: null, max_one_time_fees_usd: null } };
    expect(parseRoleCard(unbounded)).toEqual(unbounded);
  });

  it("refuses a malformed card with the reason, never a repaired one", () => {
    expect(parseRoleCard(null)).toBe("the answer is not a card");
    expect(parseRoleCard({ ...CARD, goal: 7 })).toBe("a card without its company, persona or goal");
    expect(parseRoleCard({ ...CARD, facts: [{ key: "a", value: 1, identity: true, shareable: true }] })).toBe("a malformed fact on the card");
    expect(parseRoleCard({ ...CARD, approval: { max_monthly_price_usd: 64, max_term_months: 12, max_one_time_fees_usd: "0" } })).toBe(
      "malformed approval limits on the card",
    );
    expect(parseRoleCard({ ...CARD, stop: { trigger: "after_card", text_hint: "x", change: { a: 1 } } })).toBe("a malformed stop on the card");
  });

  it("groups the facts: give these when asked (identity), then every other fact you know, budget included", () => {
    expect(factRows(CARD.facts)).toEqual({
      identity: [["Account holder name", "Sam Doe"]],
      other: [
        ["Competitor price usd", "55"],
        ["Budget max monthly usd", "60"],
      ],
    });
    expect(factLabel("tenure_years")).toBe("Tenure years");
  });

  it("shows what you would approve as sent, a zero fee as none, and leaves an unbounded limit out", () => {
    expect(approvalRows(CARD.approval as NonNullable<RoleCard["approval"]>)).toEqual([
      ["Monthly price", "up to $64.00"],
      ["Contract", "up to 12 months"],
      ["One-time fees", "none"],
    ]);
    expect(approvalRows({ max_monthly_price_usd: "70", max_term_months: null, max_one_time_fees_usd: "25" })).toEqual([
      ["Monthly price", "up to $70"],
      ["One-time fees", "up to $25"],
    ]);
  });

  it("says when the stop is due, and an unknown trigger raw", () => {
    expect(stopWhen("after_card")).toBe("Once you have seen an approval card");
    expect(stopWhen("after_lunch")).toBe("after_lunch");
  });

  it("asks the task's card with its ref encoded, and a case's under its own case path", () => {
    expect(paths.taskCard("cp-direct-discount@1:full#3")).toBe("/api/tasks/card?ref=cp-direct-discount%401%3Afull%233");
    expect(paths.caseCard("run-1")).toBe("/api/cases/run-1/card");
  });
});
