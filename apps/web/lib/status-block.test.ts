import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import type { RuntimePayload } from "./runtime-client";
import { renderStatusBlock, type StatusBlock } from "./status-block";

const caseRecord = {
  bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" } },
  case_id: "11111111-1111-4111-8111-111111111111",
  constraints: [{ classification: "hard", statement: "Do not change device financing." }],
  goal: {
    deadline: null,
    forbidden_changes: ["device_financing_change"],
    required_features: ["mobile_hotspot"],
    target_monthly_total: { amount_minor: 7500, currency: "USD" },
  },
};

const offer = {
  expires_at: "2026-09-25T12:00:00Z",
  features: ["mobile_hotspot", "unlimited_talk_text"],
  fees: [],
  monthly_price: { amount_minor: 7200, currency: "USD" },
  offer_id: "33333333-3333-4333-8333-333333333333",
  provider_id: "fictional_mobile_provider",
  revision: 1,
  term_months: 1,
  total_cost: { amount_minor: 7200, currency: "USD" },
};

const PENDING_EXPIRES_AT = "2026-09-24T18:30:00Z";
const NOT_VERIFIED = "Stopped — state not verified. Reconnect or restart the local demo.";

const pendingApproval = {
  action_intent_revision: 1,
  approval_id: "22222222-2222-4222-8222-222222222222",
  case_revision: 2,
  decision: "pending",
  expires_at: PENDING_EXPIRES_AT,
  material_terms_hash: "hash-1",
};

function payload(
  overrides: Partial<RuntimePayload> = {},
  snapshot: Record<string, unknown> = {},
): RuntimePayload {
  return {
    approval: null,
    case: caseRecord,
    case_id: "11111111-1111-4111-8111-111111111111",
    completion: {
      decision: "not_done",
      evidence_ids: [],
      reason_codes: ["approval_or_execution_pending"],
    },
    event_cursor: 1,
    evidence: [],
    execution_count: 0,
    revision: 2,
    route: "slow_refresh",
    snapshot: { case: caseRecord, offers: [], phase: "strategy", ...snapshot },
    ...overrides,
  };
}

function row(block: StatusBlock, label: string): string | undefined {
  return block.rows.find((item) => item.label === label)?.value;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("renderStatusBlock", () => {
  it("renders the rows in a fixed order", () => {
    expect(renderStatusBlock(payload()).rows.map((item) => item.label)).toEqual([
      "Phase",
      "Goal",
      "Constraints",
      "Current offer",
      "Approval",
      "Execution",
      "Completion",
    ]);
  });

  it("renders a planning Case with no offer and no approval", () => {
    const block = renderStatusBlock(payload());
    expect(block.doingNow).toBe("Planning from your confirmed goal.");
    expect(row(block, "Phase")).toBe("Strategy");
    expect(row(block, "Current offer")).toBe("No offer yet");
    expect(row(block, "Approval")).toBe("None");
    expect(row(block, "Execution")).toBe("Not started");
    expect(row(block, "Completion")).toBe("Not Done · Approval Or Execution Pending");
  });

  it("renders the projected goal and constraints", () => {
    const block = renderStatusBlock(payload());
    expect(row(block, "Goal")).toBe("$75.00 or below per month (current bill $92.00)");
    expect(row(block, "Constraints")).toBe(
      "Keep: Mobile Hotspot · Never change: Device Financing Change · Hard: Do not change device financing.",
    );
  });

  it("names the goal deadline when the projection carries one", () => {
    const withDeadline = { ...caseRecord, goal: { ...caseRecord.goal, deadline: "2026-10-01T00:00:00Z" } };
    const block = renderStatusBlock(payload({}, { case: withDeadline }));
    expect(row(block, "Goal")).toBe(
      "$75.00 or below per month (current bill $92.00) · by 2026-10-01T00:00:00Z",
    );
  });

  it("renders a negotiating Case with the current offer's material terms", () => {
    const fee = { amount: { amount_minor: 1000, currency: "USD" }, category: "one_time", name: "activation" };
    const block = renderStatusBlock(payload({}, {
      offers: [{ ...offer, fees: [fee], total_cost: { amount_minor: 8200, currency: "USD" } }],
      phase: "negotiating",
    }));
    expect(block.doingNow).toBe("Negotiating with the fictional Provider.");
    expect(row(block, "Phase")).toBe("Negotiating");
    expect(row(block, "Current offer")).toBe(
      "fictional_mobile_provider · $72.00/month · total $82.00 · fees: Activation $10.00 · 1 months · Mobile Hotspot, Unlimited Talk Text · offer expires 2026-09-25T12:00:00Z · offer revision 1",
    );
  });

  it("renders a pending approval with its expiry", () => {
    const block = renderStatusBlock(payload(
      { approval: pendingApproval, revision: 4, route: "wait_for_approval" },
      { offers: [offer], phase: "awaiting_approval" },
    ));
    expect(block.doingNow).toBe("Waiting for your approval of the exact terms.");
    expect(row(block, "Phase")).toBe("Awaiting Approval");
    expect(row(block, "Approval")).toBe(`Pending · expires ${PENDING_EXPIRES_AT}`);
    expect(row(block, "Current offer")).toContain("no fees");
    expect(row(block, "Execution")).toBe("Not started");
  });

  it("renders a pending execution after approval", () => {
    const block = renderStatusBlock(payload(
      { approval: { ...pendingApproval, decision: "approved" }, revision: 5 },
      { offers: [offer], pending_execution: true, phase: "negotiating" },
    ));
    expect(block.doingNow).toBe(
      "Executing the approved fictional transition; waiting for a verified result.",
    );
    expect(row(block, "Approval")).toBe("Approved");
    expect(row(block, "Execution")).toBe("In progress");
  });

  it("renders a verified completion with its receipt", () => {
    const block = renderStatusBlock(payload(
      {
        approval: { ...pendingApproval, decision: "approved" },
        completion: { decision: "complete", evidence_ids: ["evidence-1"], reason_codes: [] },
        evidence: [{ evidence_id: "evidence-1" }],
        execution_count: 1,
        revision: 7,
        route: "terminal",
      },
      { offers: [offer], pending_execution: false, phase: "complete" },
    ));
    expect(block.doingNow).toBe("Done: the Runtime verified completion against Provider Evidence.");
    expect(row(block, "Phase")).toBe("Complete");
    expect(row(block, "Execution")).toBe("Executed 1 time");
    expect(row(block, "Completion")).toBe("Verified complete · 1 matching Evidence ID · receipt shown");
  });

  it("does not render a completion without matching Evidence as verified", () => {
    const block = renderStatusBlock(payload(
      {
        completion: { decision: "complete", evidence_ids: ["evidence-9"], reason_codes: [] },
        evidence: [{ evidence_id: "evidence-1" }],
        execution_count: 1,
      },
      { offers: [offer], phase: "complete" },
    ));
    expect(block.doingNow).toBe(NOT_VERIFIED);
    expect(row(block, "Completion")).toBe("Complete claimed without matching Evidence · no receipt");
  });

  it("renders an expired approval as stopped even though the phase is negotiating", () => {
    const block = renderStatusBlock(payload(
      {
        approval: { ...pendingApproval, decision: "expired" },
        completion: { decision: "not_done", evidence_ids: [], reason_codes: ["approval_expired"] },
      },
      { offers: [offer], phase: "negotiating" },
    ));
    expect(block.doingNow).toBe("Stopped: the approval expired and nothing was accepted.");
    expect(row(block, "Approval")).toBe(`Expired at ${PENDING_EXPIRES_AT}`);
    expect(row(block, "Completion")).toBe("Not Done · Approval Expired");
  });

  it("renders a rejected approval as not verified, as the workspace Blocks it", () => {
    const block = renderStatusBlock(payload(
      { approval: { ...pendingApproval, decision: "rejected" } },
      { offers: [offer], phase: "negotiating" },
    ));
    expect(block.doingNow).toBe(NOT_VERIFIED);
    expect(row(block, "Approval")).toBe("Rejected");
  });

  it.each([
    ["initiated", "Planning from your confirmed goal."],
    ["candidate_complete", "Waiting for the Runtime."],
    ["closed", "Waiting for the Runtime."],
  ])("maps phase %s with no approval to its doing-now line", (phase, line) => {
    expect(renderStatusBlock(payload({}, { phase })).doingNow).toBe(line);
  });

  // Review I-1: the bar follows the workspace's phaseForPayload.
  it.each([
    ["no material_terms_hash", { ...pendingApproval, material_terms_hash: undefined }],
    ["an unparseable expiry", { ...pendingApproval, expires_at: "not-a-date" }],
  ])("renders a pending approval with %s as not verified", (_name, invalid) => {
    const block = renderStatusBlock(payload(
      { approval: invalid },
      { offers: [offer], phase: "awaiting_approval" },
    ));
    expect(block.doingNow).toBe(NOT_VERIFIED);
  });

  it("renders approved, not pending, not done as not verified", () => {
    const block = renderStatusBlock(payload(
      { approval: { ...pendingApproval, decision: "approved" } },
      { offers: [offer], pending_execution: false, phase: "negotiating" },
    ));
    expect(block.doingNow).toBe(NOT_VERIFIED);
  });

  it("claims no activity for a terminal candidate_complete Case", () => {
    const block = renderStatusBlock(payload(
      {
        approval: { ...pendingApproval, decision: "approved" },
        completion: { decision: "candidate_complete", evidence_ids: ["evidence-1"], reason_codes: [] },
        evidence: [{ evidence_id: "evidence-1" }],
        execution_count: 1,
      },
      { offers: [offer], pending_execution: false, phase: "candidate_complete" },
    ));
    expect(block.doingNow).toBe(NOT_VERIFIED);
    expect(block.doingNow).not.toMatch(/checking/i);
    expect(row(block, "Completion")).toBe("Candidate Complete");
  });

  it("renders a held payload as not verified when the workspace is Blocked", () => {
    const valid = payload({ approval: pendingApproval, revision: 4 }, { offers: [offer], phase: "awaiting_approval" });
    expect(renderStatusBlock(valid).doingNow).toBe("Waiting for your approval of the exact terms.");
    const block = renderStatusBlock(valid, { blocked: true });
    expect(block.doingNow).toBe(NOT_VERIFIED);
    expect(block.asOf).toBe("as of Case revision 4");
  });

  // Review I-2: same condition as the Progress artifact title (M-4).
  it.each([
    ["pending", { ...pendingApproval }],
    ["null", null],
  ])("says finalizing, not executing an approval, when the decision is %s", (_name, current) => {
    const block = renderStatusBlock(payload(
      { approval: current },
      { offers: [offer], pending_execution: true, phase: "negotiating" },
    ));
    expect(block.doingNow).toBe("Finalizing the fictional transition; waiting for a verified result.");
  });

  it("names the Case revision the bar was rendered from", () => {
    expect(renderStatusBlock(payload({ revision: 9 })).asOf).toBe("as of Case revision 9");
  });

  it("renders a fallback for empty decision strings", () => {
    const block = renderStatusBlock(payload({
      approval: { ...pendingApproval, decision: "" },
      completion: { decision: "", evidence_ids: [] },
    }));
    expect(row(block, "Approval")).toBe("Not reported");
    expect(row(block, "Completion")).toBe("Not reported");
  });

  it("uses the Offer artifact's wording for an unnamed Provider", () => {
    const block = renderStatusBlock(payload({}, { offers: [{ ...offer, provider_id: undefined }] }));
    expect(row(block, "Current offer")).toMatch(/^Fictional Provider · \$72\.00\/month/);
  });

  it("falls back when the projection carries no phase", () => {
    const block = renderStatusBlock(payload({}, { phase: undefined }));
    expect(block.doingNow).toBe("Waiting for the Runtime to report the Case phase.");
    expect(row(block, "Phase")).toBe("Not reported");
  });

  it("is deterministic: the same payload renders the same rows at any time", () => {
    const input = payload({ approval: pendingApproval }, { offers: [offer], phase: "awaiting_approval" });
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    const early = renderStatusBlock(input);
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    const late = renderStatusBlock(input);
    expect(late).toEqual(early);
  });

  it("never renders from fast", () => {
    const sentinel = "FAST ECHO MUST NOT RENDER";
    const block = renderStatusBlock(payload(
      {
        approval: pendingApproval,
        fast: { created_at: "2026-09-24T00:00:00Z", dialogue_act: "clarify", response_text: sentinel },
      },
      { offers: [offer], phase: "awaiting_approval" },
    ));
    const text = [block.doingNow, ...block.rows.map((item) => `${item.label} ${item.value}`)].join("\n");
    expect(text).not.toContain(sentinel);
    expect(text).not.toContain("clarify");
  });
});

// PR-8 I12 on the Web side: the renderer never reads `fast`, and it is a
// display module for the conversation surface only.
describe("status-block module boundary", () => {
  const libDir = import.meta.dirname;
  const webRoot = join(libDir, "..");

  function sourceFiles(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" || entry.name.startsWith(".") ? [] : sourceFiles(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  }

  it("does not mention fast in its source", () => {
    const source = readFileSync(join(libDir, "status-block.ts"), "utf8");
    expect(source).not.toMatch(/\bfast\b/i);
  });

  it("is imported only by the conversation workspace", () => {
    const importers = [join(webRoot, "app"), join(webRoot, "lib")]
      .flatMap(sourceFiles)
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        return /from\s+["'][^"']*status-block["']/.test(source) ||
          /import\s*\(\s*["'`][^"'`]*status-block["'`]\s*\)/.test(source);
      })
      .map((path) => relative(webRoot, path));
    expect(importers).toEqual(["app/components/conversation-workspace.tsx"]);
  });
});
