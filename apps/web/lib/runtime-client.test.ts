import { afterEach, describe, expect, it, vi } from "vitest";

import {
  completionHasVerifiedEvidence,
  createCase,
  decideApproval,
  hasValidTaskBrief,
  type IntakeFacts,
} from "./runtime-client";

const facts: IntakeFacts = {
  currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
  targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
  mobileHotspotRequired: true,
  deviceFinancingChangeForbidden: true,
};

const caseRecord = {
  bill_snapshot: { monthly_total: facts.currentMonthlyTotal },
  case_id: "11111111-1111-4111-8111-111111111111",
  constraints: [{ classification: "hard", statement: "Do not change device financing." }],
  goal: {
    forbidden_changes: ["device_financing_change"],
    required_features: ["mobile_hotspot"],
    target_monthly_total: facts.targetMonthlyTotal,
  },
};

const basePayload = {
  approval: null,
  case: caseRecord,
  case_id: "11111111-1111-4111-8111-111111111111",
  completion: { decision: "not_done", evidence_ids: [] },
  event_cursor: 1,
  evidence: [],
  execution_count: 0,
  revision: 2,
  route: "slow_refresh",
  snapshot: { case: caseRecord },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("runtime client", () => {
  it("rejects malformed success payloads", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));

    await expect(createCase(facts)).rejects.toMatchObject({
      kind: "invalid",
    });
  });

  it.each(["", "   "])('rejects an evidence item with an empty evidence_id: "%s"', async (evidenceId) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...basePayload, evidence: [{ evidence_id: evidenceId }] }), { status: 200 }),
    ));

    await expect(createCase(facts)).rejects.toMatchObject({ kind: "invalid" });
  });

  it.each([
    [409, "http"],
    [503, "http"],
  ] as const)("fails closed for HTTP %s", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status })));

    await expect(createCase(facts)).rejects.toMatchObject({ kind, status });
  });

  it("fails closed when the local Runtime cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(createCase(facts)).rejects.toMatchObject({
      kind: "network",
      status: null,
    });
  });

  it("serializes exactly the four confirmed intake facts", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(basePayload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createCase(facts);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/cases",
      expect.objectContaining({
        body: JSON.stringify({
          current_monthly_total: facts.currentMonthlyTotal,
          target_monthly_total: facts.targetMonthlyTotal,
          mobile_hotspot_required: true,
          device_financing_change_forbidden: true,
        }),
        method: "POST",
      }),
    );
  });

  it("fails closed for root, snapshot, draft, and later fact disagreement", () => {
    expect(hasValidTaskBrief(basePayload, facts)).toBe(true);
    expect(hasValidTaskBrief({ ...basePayload, case_id: "other" }, facts)).toBe(false);
    expect(hasValidTaskBrief({
      ...basePayload,
      snapshot: { case: { ...caseRecord, case_id: "other" } },
    }, facts)).toBe(false);
    expect(hasValidTaskBrief({
      ...basePayload,
      case: { ...caseRecord, goal: { ...caseRecord.goal, target_monthly_total: { amount_minor: 7400, currency: "USD" } } },
    }, facts)).toBe(false);
    expect(hasValidTaskBrief({
      ...basePayload,
      snapshot: { case: { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } } },
    }, facts)).toBe(false);
  });

  it("sends the returned approval pins without inventing revisions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        ...basePayload,
        approval: {
          action_intent_revision: 3,
          approval_id: "22222222-2222-4222-8222-222222222222",
          case_revision: 4,
          decision: "approved",
          expires_at: "2026-08-25T13:00:00Z",
          material_terms_hash: "hash-1",
        },
      }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await decideApproval("case/id", "approval/id", {
      expectedActionIntentRevision: 3,
      expectedCaseRevision: 4,
      expectedRevision: 8,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/cases/case%2Fid/approvals/approval%2Fid",
      expect.objectContaining({
        body: JSON.stringify({
          decision: "approved",
          expected_action_intent_revision: 3,
          expected_case_revision: 4,
          expected_revision: 8,
        }),
        method: "POST",
      }),
    );
  });

  it("only accepts a verified complete receipt with matching evidence", () => {
    const completed = {
      ...basePayload,
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
    };
    expect(completionHasVerifiedEvidence(completed)).toBe(true);
    expect(completionHasVerifiedEvidence({ ...completed, evidence: [] })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, evidence: [{ evidence_id: "" }] })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, evidence: [{ evidence_id: "   " }] })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, completion: { decision: "complete", evidence_ids: [""] } })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, completion: { decision: "complete", evidence_ids: ["   "] } })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, execution_count: 2 })).toBe(false);
    expect(completionHasVerifiedEvidence({ ...completed, completion: { decision: "complete", evidence_ids: [] } })).toBe(false);
  });
});
