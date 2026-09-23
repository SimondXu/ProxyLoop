import { afterEach, describe, expect, it, vi } from "vitest";

import {
  appendConsumerEvent,
  checkReadiness,
  clearPersistedWorkspace,
  completionHasVerifiedEvidence,
  createCase,
  decideApproval,
  getCase,
  hasValidPendingApproval,
  hasValidTaskBrief,
  isValidPersistedWorkspace,
  loadPersistedWorkspace,
  RUNTIME_STORAGE_KEY,
  savePersistedWorkspace,
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
  window.localStorage.clear();
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

  it.each([
    [404, {}, "case_not_found", "The saved Case is no longer available in the local Runtime. Reset this local task to continue."],
    [422, { detail: { code: "request_invalid", message: "redacted" } }, "request_invalid", "The local Runtime rejected this state safely. No unverified result is shown."],
    [409, { detail: { code: "case_conflict", message: "redacted" } }, "case_conflict", "The Runtime refused this command because it conflicts with the current Case. Retry only if the action is still offered; to start over, restart the Runtime process (or reset the durable demo), then choose New task."],
    [503, { detail: { code: "temporal_unavailable", message: "redacted" } }, "temporal_unavailable", "The local orchestration attempt is still unresolved. Your Case and safe retry remain preserved; reconnect to read authoritative state."],
    [503, {}, "temporal_unavailable", "The local orchestration attempt is still unresolved. Your Case and safe retry remain preserved; reconnect to read authoritative state."],
  ] as const)("maps HTTP %s %j to category %s with its bounded copy", async (status, body, category, message) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })));

    await expect(getCase(basePayload.case_id)).rejects.toMatchObject({ kind: "http", status, category, message });
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
        headers: expect.objectContaining({ "Idempotency-Key": expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/) }),
        method: "POST",
      }),
    );
  });

  it("sends the caller-provided lowercase UUIDv4 key on each existing POST helper", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify(basePayload), { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);
    const keys = [
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
      "33333333-3333-4333-8333-333333333333",
    ];

    await createCase(facts, { idempotencyKey: keys[0] });
    await appendConsumerEvent("case", "confirm", 2, { idempotencyKey: keys[1] });
    await decideApproval("case", "approval", {
      expectedActionIntentRevision: 1,
      expectedCaseRevision: 2,
      expectedRevision: 4,
    }, { idempotencyKey: keys[2] });

    expect(fetchMock.mock.calls.map(([, init]) => (init as RequestInit).headers)).toEqual(
      keys.map((key) => expect.objectContaining({ "Idempotency-Key": key })),
    );
  });

  it("reads the Case and preserves only a strict versioned local envelope", async () => {
    const pendingCommand = {
      kind: "append_event" as const,
      idempotencyKey: "22222222-2222-4222-8222-222222222222",
      requestBody: {
        content: "Keep mobile hotspot and device financing unchanged.",
        event_type: "consumer_message",
        expected_revision: 2,
      },
      caseId: basePayload.case_id,
      expectedRevision: 2,
      approvalId: null,
      expectedCaseRevision: null,
      expectedActionIntentRevision: null,
    };
    const state = {
      schemaVersion: 1 as const,
      caseId: basePayload.case_id,
      confirmedFacts: facts,
      pendingCommand,
    };
    expect(isValidPersistedWorkspace(state)).toBe(true);
    savePersistedWorkspace(state);
    expect(window.localStorage.getItem(RUNTIME_STORAGE_KEY)).toBe(JSON.stringify(state));
    expect(loadPersistedWorkspace()).toEqual(state);

    const invalid = { ...state, unexpected: "untrusted" };
    window.localStorage.setItem(RUNTIME_STORAGE_KEY, JSON.stringify(invalid));
    expect(loadPersistedWorkspace()).toBeNull();
    clearPersistedWorkspace();
    expect(window.localStorage.getItem(RUNTIME_STORAGE_KEY)).toBeNull();
  });

  it("rejects pending commands whose body, pins, or Case locator disagree", () => {
    const pendingEvent = {
      kind: "append_event" as const,
      idempotencyKey: "22222222-2222-4222-8222-222222222222",
      requestBody: {
        content: "Keep mobile hotspot and device financing unchanged.",
        event_type: "consumer_message",
        expected_revision: 2,
      },
      caseId: basePayload.case_id,
      expectedRevision: 2,
      approvalId: null,
      expectedCaseRevision: null,
      expectedActionIntentRevision: null,
    };
    const state = {
      schemaVersion: 1 as const,
      caseId: basePayload.case_id,
      confirmedFacts: facts,
      pendingCommand: pendingEvent,
    };
    expect(isValidPersistedWorkspace(state)).toBe(true);
    expect(isValidPersistedWorkspace({
      ...state,
      pendingCommand: {
        ...pendingEvent,
        requestBody: { ...pendingEvent.requestBody, expected_revision: 3 },
      },
    })).toBe(false);
    expect(isValidPersistedWorkspace({ ...state, caseId: "33333333-3333-4333-8333-333333333333" })).toBe(false);

    const pendingApproval = {
      kind: "decide_approval" as const,
      idempotencyKey: "33333333-3333-4333-8333-333333333333",
      requestBody: {
        decision: "approved",
        expected_action_intent_revision: 1,
        expected_case_revision: 2,
        expected_revision: 4,
      },
      caseId: basePayload.case_id,
      expectedRevision: 4,
      approvalId: "22222222-2222-4222-8222-222222222222",
      expectedCaseRevision: 2,
      expectedActionIntentRevision: 1,
    };
    expect(isValidPersistedWorkspace({ ...state, pendingCommand: pendingApproval })).toBe(true);
    expect(isValidPersistedWorkspace({
      ...state,
      pendingCommand: {
        ...pendingApproval,
        requestBody: { ...pendingApproval.requestBody, expected_action_intent_revision: 2 },
      },
    })).toBe(false);

    const pendingCreate = {
      kind: "create_case" as const,
      idempotencyKey: "44444444-4444-4444-8444-444444444444",
      requestBody: {
        current_monthly_total: facts.currentMonthlyTotal,
        target_monthly_total: facts.targetMonthlyTotal,
        mobile_hotspot_required: true,
        device_financing_change_forbidden: true,
      },
      caseId: null,
      expectedRevision: null,
      approvalId: null,
      expectedCaseRevision: null,
      expectedActionIntentRevision: null,
    };
    const createState = { ...state, caseId: null, pendingCommand: pendingCreate };
    expect(isValidPersistedWorkspace(createState)).toBe(true);
    expect(isValidPersistedWorkspace({
      ...createState,
      pendingCommand: {
        ...pendingCreate,
        requestBody: {
          ...pendingCreate.requestBody,
          target_monthly_total: { amount_minor: 7400, currency: "USD" },
        },
      },
    })).toBe(false);
  });

  it("gets readiness without exposing arbitrary error bodies", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      secret: "must not escape the narrow readiness shape",
    }), { status: 200 })));

    await expect(checkReadiness()).resolves.toEqual({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      error_category: "none",
    });
  });

  it("returns the stable category for an unavailable readiness response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "unavailable",
      ready: false,
      dependency: "postgres",
      detail: { code: "dependency_not_ready", message: "redacted" },
    }), { status: 503 })));

    await expect(checkReadiness()).resolves.toMatchObject({
      ready: false,
      error_category: "dependency_not_ready",
    });
  });

  it("reports the direct readiness profile with its orchestration mode", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: "ok",
      ready: true,
      dependency: "memory",
      adapter_mode: "scripted",
      storage_mode: "memory",
      orchestration_mode: "direct",
    }), { status: 200 })));

    await expect(checkReadiness()).resolves.toEqual({
      status: "ok",
      ready: true,
      dependency: "memory",
      adapter_mode: "scripted",
      storage_mode: "memory",
      orchestration_mode: "direct",
      error_category: "none",
    });
  });

  it("does not promise a Case read in the case_conflict copy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: "case already exists",
    }), { status: 409 })));

    const rejected = await createCase(facts).catch((caught: unknown) => caught);

    expect(rejected).toMatchObject({ category: "case_conflict", status: 409 });
    expect((rejected as Error).message).not.toMatch(/I read|I will read|Reconnect/);
    expect((rejected as Error).message).toContain("restart the Runtime process");
  });

  it("returns ready:false with the Temporal category when orchestration is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: { code: "temporal_unavailable", message: "redacted" },
    }), { status: 503 })));

    await expect(checkReadiness()).resolves.toEqual({
      status: "unavailable",
      ready: false,
      dependency: "runtime",
      error_category: "temporal_unavailable",
    });
  });

  it("reads a Case through the narrow GET helper", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(basePayload), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getCase(basePayload.case_id)).resolves.toEqual(basePayload);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/runtime/cases/11111111-1111-4111-8111-111111111111",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("accepts the API's allow-listed browser projection with no internal fields", async () => {
    const projectedCase = {
      bill_snapshot: { monthly_total: facts.currentMonthlyTotal },
      case_id: basePayload.case_id,
      constraints: [{ classification: "hard", statement: "Do not change device financing." }],
      goal: {
        deadline: "2026-10-02T12:00:00Z",
        desired_outcome: "Reduce the recurring bill without losing mobile hotspot access.",
        forbidden_changes: ["device_financing_change"],
        required_features: ["mobile_hotspot"],
        target_monthly_total: facts.targetMonthlyTotal,
      },
      phase: "awaiting_approval",
      revision: 1,
    };
    const completion = {
      decision: "not_done",
      evidence_ids: [],
      missing_evidence: ["verified_provider_confirmation"],
      reason_codes: ["approval_or_execution_pending"],
    };
    const projected = {
      approval: {
        action_intent_revision: 1,
        action_type: "accept_offer",
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 1,
        decided_at: null,
        decision: "pending",
        expires_at: "2026-08-25T13:00:00Z",
        material_terms_hash: "a".repeat(64),
        offer_ref: { offer_id: "33333333-3333-4333-8333-333333333333", offer_revision: 1 },
        requested_at: "2026-08-25T12:00:00Z",
      },
      case: projectedCase,
      case_id: basePayload.case_id,
      completion,
      event_cursor: 2,
      evidence: [],
      execution_count: 0,
      fast: {
        created_at: "2026-08-25T12:00:00Z",
        dialogue_act: "clarify",
        response_text: "I found an offer that needs your approval.",
      },
      revision: 4,
      route: "wait_for_approval",
      snapshot: {
        case: projectedCase,
        completion,
        event_cursor: 2,
        offers: [{
          expires_at: "2026-08-25T13:00:00Z",
          features: ["mobile_hotspot", "unlimited_talk_text"],
          fees: [],
          monthly_price: { amount_minor: 7200, currency: "USD" },
          offer_id: "33333333-3333-4333-8333-333333333333",
          provider_id: "pine-mobile",
          revision: 1,
          term_months: 0,
          total_cost: { amount_minor: 86400, currency: "USD" },
        }],
        pending_execution: false,
        phase: "awaiting_approval",
        revision: 4,
        visible_events: [{
          actor: "consumer",
          content: "Please review the current offer.",
          event_cursor: 2,
          event_type: "consumer_message",
          occurred_at: "2026-08-25T12:00:00Z",
        }],
      },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify(projected), { status: 200 }),
    ));

    const parsed = await getCase(basePayload.case_id);

    expect(parsed).toEqual(projected);
    expect(hasValidTaskBrief(parsed, facts)).toBe(true);
    expect(hasValidPendingApproval(parsed)).toBe(true);
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
