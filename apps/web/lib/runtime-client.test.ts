import { afterEach, describe, expect, it, vi } from "vitest";

import {
  completionHasVerifiedEvidence,
  createCase,
  decideApproval,
} from "./runtime-client";

const basePayload = {
  approval: null,
  case: {},
  case_id: "11111111-1111-4111-8111-111111111111",
  completion: { decision: "not_done", evidence_ids: [] },
  event_cursor: 1,
  evidence: [],
  execution_count: 0,
  revision: 2,
  route: "slow_refresh",
  snapshot: {},
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("runtime client", () => {
  it("rejects malformed success payloads", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json", { status: 200 })));

    await expect(createCase()).rejects.toMatchObject({
      kind: "invalid",
    });
  });

  it.each(["", "   "])('rejects an evidence item with an empty evidence_id: "%s"', async (evidenceId) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ...basePayload, evidence: [{ evidence_id: evidenceId }] }), { status: 200 }),
    ));

    await expect(createCase()).rejects.toMatchObject({ kind: "invalid" });
  });

  it.each([
    [409, "http"],
    [503, "http"],
  ] as const)("fails closed for HTTP %s", async (status, kind) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status })));

    await expect(createCase()).rejects.toMatchObject({ kind, status });
  });

  it("fails closed when the local Runtime cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network down")));

    await expect(createCase()).rejects.toMatchObject({
      kind: "network",
      status: null,
    });
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
