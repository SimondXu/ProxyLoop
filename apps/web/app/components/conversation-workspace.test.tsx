import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationWorkspace, isSupportedMobileBillIntent } from "./conversation-workspace";
import type { RuntimePayload } from "../../lib/runtime-client";

const offer = {
  features: ["mobile_hotspot", "unlimited_talk_text"],
  monthly_price: { amount_minor: 7200, currency: "USD" },
  provider_id: "fictional_mobile_provider",
  term_months: 1,
};

const caseRecord = {
  bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" }, usage: {} },
  case_id: "11111111-1111-4111-8111-111111111111",
  constraints: [{ classification: "hard", statement: "Do not change device financing." }],
  goal: {
    forbidden_changes: ["device_financing_change"],
    required_features: ["mobile_hotspot"],
    target_monthly_total: { amount_minor: 7500, currency: "USD" },
  },
};

function payload(overrides: Partial<RuntimePayload> = {}): RuntimePayload {
  return {
    approval: null,
    case: caseRecord,
    case_id: "11111111-1111-4111-8111-111111111111",
    completion: { decision: "not_done", evidence_ids: [] },
    event_cursor: 1,
    evidence: [],
    execution_count: 0,
    revision: 2,
    route: "slow_refresh",
    snapshot: {
      case: caseRecord,
      offers: [offer],
    },
    ...overrides,
  };
}

const NORMAL_PENDING_APPROVAL_EXPIRES_AT = new Date(Date.now() + 60 * 60 * 1000).toISOString();

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  vi.useRealTimers();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.clearAllMocks();
});

vi.mock("../../lib/runtime-client", async () => {
  const actual = await vi.importActual<typeof import("../../lib/runtime-client")>("../../lib/runtime-client");
  return {
    ...actual,
    appendConsumerEvent: vi.fn(),
    checkReadiness: vi.fn(),
    createCase: vi.fn(),
    decideApproval: vi.fn(),
    getCase: vi.fn(),
  };
});

describe("ConversationWorkspace", () => {
  async function completeLocalIntake(
    create = true,
    financing = "yes",
    expectReady = true,
    authoritativeResponses: RuntimePayload[] = [payload()],
  ) {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.getCase).mockReset();
    authoritativeResponses.forEach((response) => vi.mocked(runtime.getCase).mockResolvedValueOnce(response));
    const composer = screen.getByPlaceholderText("Message ProxyLoop");
    fireEvent.change(composer, { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$92" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$75" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "yes" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: financing } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    if (expectReady) {
      expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    }
    if (create) {
      fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
      await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
    }
  }

  it.each([
    "Help me plan a vacation",
    "What is my phone price?",
    "my mobile cost increased",
  ])("keeps unsupported initial request %s local and does not create a Case", async (text) => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockClear();

    render(<ConversationWorkspace />);
    const composer = screen.getByPlaceholderText("Message ProxyLoop");
    fireEvent.change(composer, { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText(/only supports lowering a fictional mobile bill/)).toBeInTheDocument();
    expect(runtime.createCase).not.toHaveBeenCalled();
    expect(composer).toBeEnabled();
  });

  it.each([
    "Lower my mobile bill",
    "Save on my phone bill",
  ])("accepts supported mobile-bill intent: %s", (text) => {
    expect(isSupportedMobileBillIntent(text)).toBe(true);
  });

  it("keeps edits unresolved until a valid correction, then sends corrected facts", async () => {
    const runtime = await import("../../lib/runtime-client");
    const correctedCase = {
      ...caseRecord,
      bill_snapshot: {
        ...caseRecord.bill_snapshot,
        monthly_total: { amount_minor: 8000, currency: "USD" },
      },
    };
    vi.mocked(runtime.createCase).mockResolvedValue(payload({
      case: correctedCase,
      snapshot: { case: correctedCase, offers: [offer] },
    }));
    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    const createButton = screen.getByRole("button", { name: "Create fictional Case" });
    const editButtons = screen.getAllByRole("button", { name: "Edit" });
    fireEvent.click(editButtons[0]);
    expect(createButton).toBeDisabled();

    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$74" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/stay above the confirmed target/);
    expect(createButton).toBeDisabled();
    expect(screen.getByText("$92.00")).toBeInTheDocument();
    expect(runtime.createCase).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$80" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(createButton).toBeEnabled();
    vi.mocked(runtime.getCase).mockReset();
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      case: correctedCase,
      snapshot: { case: correctedCase, offers: [offer] },
    }));
    fireEvent.click(createButton);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
    expect(runtime.createCase).toHaveBeenCalledWith(
      {
        currentMonthlyTotal: { amount_minor: 8000, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      { idempotencyKey: expect.any(String) },
    );
  });

  it("accepts financing no change as a positive confirmation", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, "no change");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
    expect(runtime.createCase).toHaveBeenCalledWith(
      expect.objectContaining({ deviceFinancingChangeForbidden: true }),
      { idempotencyKey: expect.any(String) },
    );
  });

  it("rejects contradictory financing no-change language locally", async () => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, "no change, but I want to change device financing", false);

    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Device financing must remain unchanged/);
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("rejects Terra's contradictory financing no-change regression locally", async () => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, "no change, but please modify device financing", false);

    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("rejects contradictory hotspot language locally", async () => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    const composer = screen.getByPlaceholderText("Message ProxyLoop");
    fireEvent.change(composer, { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$92" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "$75" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "yes, remove mobile hotspot" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Mobile hotspot must remain required/);
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("keeps the conversation primary and completes only through the Runtime flow", async () => {
    const runtime = await import("../../lib/runtime-client");
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    });
    const completed = payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      revision: 7,
      route: "terminal",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockResolvedValue(completed);

    render(<ConversationWorkspace />);
    await waitFor(() => expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled());
    await completeLocalIntake(true, "yes", true, [payload(), waiting, completed]);

    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Approve exact terms" }));
    expect(await screen.findByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    expect(screen.getAllByText("Verified").length).toBeGreaterThan(0);
    expect(runtime.decideApproval).toHaveBeenCalledWith(
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
      {
        expectedActionIntentRevision: 1,
        expectedCaseRevision: 2,
        expectedRevision: 4,
      },
      { idempotencyKey: expect.any(String) },
    );
  });

  it("does not render success for a terminal payload whose evidence does not match", async () => {
    const runtime = await import("../../lib/runtime-client");
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    });
    const invalidCompleted = payload({
      completion: { decision: "complete", evidence_ids: ["missing"] },
      execution_count: 1,
      route: "terminal",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockResolvedValue(invalidCompleted);

    render(<ConversationWorkspace />);
    await waitFor(() => expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled());
    await completeLocalIntake(true, "yes", true, [payload(), waiting, invalidCompleted]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve exact terms" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByText("Completed with supporting Evidence")).not.toBeInTheDocument();
  });

  it("blocks a malformed Task Brief without offering confirmation or sending an event", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload({
      snapshot: {
        case: {
          bill_snapshot: { monthly_total: { amount_minor: Number.NaN, currency: "USD" } },
          goal: {
            forbidden_changes: ["device_financing_change"],
            required_features: [],
            target_monthly_total: { amount_minor: 7500, currency: "USD" },
          },
        },
        offers: [offer],
      },
    }));

    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    vi.mocked(runtime.getCase).mockReset();
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      snapshot: {
        case: {
          bill_snapshot: { monthly_total: { amount_minor: Number.NaN, currency: "USD" } },
          goal: {
            forbidden_changes: ["device_financing_change"],
            required_features: [],
            target_monthly_total: { amount_minor: 7500, currency: "USD" },
          },
        },
        offers: [offer],
      },
    }));
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(runtime.appendConsumerEvent).not.toHaveBeenCalled();
  });

  it("blocks an incomplete pending offer without rendering an approval button", async () => {
    const runtime = await import("../../lib/runtime-client");
    const incomplete = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
      },
      revision: 4,
      route: "wait_for_approval",
      snapshot: {
        case: payload().snapshot.case,
        offers: [{ features: [], monthly_price: { amount_minor: 7200 }, provider_id: "", term_months: 1 }],
      },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(incomplete);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), incomplete]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("blocks a pending offer when its event response loses the Task Brief", async () => {
    const runtime = await import("../../lib/runtime-client");
    const lostBrief = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
      snapshot: {
        case: { bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" } } },
        offers: [offer],
      },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(lostBrief);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), lostBrief]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("blocks a structurally valid event response that drifts an intake Money fact", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    const driftedCase = {
      ...caseRecord,
      bill_snapshot: {
        ...caseRecord.bill_snapshot,
        monthly_total: { amount_minor: 9300, currency: "USD" },
      },
    };
    const drifted = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
      snapshot: { case: driftedCase, offers: [offer] },
    });
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(drifted);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), drifted]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("ignores a create response that resolves after restart", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingCreate = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockReturnValue(pendingCreate.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await screen.findByText(/sending the four confirmed intake facts/);
    fireEvent.click(screen.getByRole("button", { name: /New task/ }));

    await act(async () => {
      pendingCreate.resolve(payload());
      await pendingCreate.promise;
    });

    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled();
  });

  it("ignores an approval response that resolves after restart", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingApproval = deferred<RuntimePayload>();
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReturnValue(pendingApproval.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), waiting]);
    fireEvent.click(await screen.findByRole("button", { name: /Keep both unchanged/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve exact terms" }));
    fireEvent.click(screen.getByRole("button", { name: /New task/ }));

    await act(async () => {
      pendingApproval.resolve(payload({
        completion: { decision: "complete", evidence_ids: ["evidence-1"] },
        evidence: [{ evidence_id: "evidence-1" }],
        execution_count: 1,
        revision: 7,
        route: "terminal",
      }));
      await pendingApproval.promise;
    });

    expect(screen.queryByRole("heading", { name: "Completed with supporting Evidence" })).not.toBeInTheDocument();
  });

  it("ignores an event response that resolves after restart", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake();
    fireEvent.click(await screen.findByRole("button", { name: /Keep both unchanged/ }));
    fireEvent.click(screen.getByRole("button", { name: /New task/ }));

    await act(async () => {
      pendingEvent.resolve(payload({
        approval: {
          action_intent_revision: 1,
          approval_id: "22222222-2222-4222-8222-222222222222",
          case_revision: 2,
          decision: "pending",
          expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
          material_terms_hash: "hash-1",
        },
        revision: 4,
        route: "wait_for_approval",
      }));
      await pendingEvent.promise;
    });

    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Completed with supporting Evidence" })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled();
  });

  it("restores a stored Case only after the durable readiness profile and authoritative GET", async () => {
    const runtime = await import("../../lib/runtime-client");
    const stored = {
      schemaVersion: 1 as const,
      caseId: payload().case_id,
      confirmedFacts: {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" as const },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" as const },
        mobileHotspotRequired: true as const,
        deviceFinancingChangeForbidden: true as const,
      },
      pendingCommand: null,
    };
    runtime.savePersistedWorkspace(stored);
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      error_category: "none",
    });
    vi.mocked(runtime.getCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument();
    expect(runtime.checkReadiness).toHaveBeenCalledTimes(1);
    expect(runtime.getCase).toHaveBeenCalledWith(payload().case_id);
  });

  it("keeps the exact pending create key and body across a network retry", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockRejectedValueOnce(new runtime.RuntimeClientError("offline", "network"));
    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    const pending = runtime.loadPersistedWorkspace()?.pendingCommand;
    expect(pending?.kind).toBe("create_case");

    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      error_category: "none",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.getCase).mockResolvedValue(payload());
    fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
    await waitFor(() => expect(runtime.createCase).toHaveBeenCalledTimes(2));
    expect(vi.mocked(runtime.createCase).mock.calls[1]?.[1]).toEqual({
      idempotencyKey: pending?.idempotencyKey,
    });
    await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
  });

  it("reloads a pending event with the exact persisted key and body", async () => {
    const runtime = await import("../../lib/runtime-client");
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockRejectedValueOnce(new runtime.RuntimeClientError("offline", "network"));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload()]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    const pending = runtime.loadPersistedWorkspace()?.pendingCommand;
    expect(pending?.kind).toBe("append_event");

    cleanup();
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      error_category: "none",
    });
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.getCase).mockReset()
      .mockResolvedValueOnce(payload())
      .mockResolvedValueOnce(waiting);
    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(vi.mocked(runtime.getCase).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(runtime.appendConsumerEvent).mock.invocationCallOrder[0] ?? Infinity,
    );
    expect(vi.mocked(runtime.appendConsumerEvent).mock.calls).toHaveLength(1);
    expect(vi.mocked(runtime.appendConsumerEvent).mock.calls[0]).toEqual([
      pending?.caseId,
      pending?.requestBody.content,
      pending?.expectedRevision,
      { idempotencyKey: pending?.idempotencyKey },
    ]);
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("reloads a pending approval with the exact persisted key and pins", async () => {
    const runtime = await import("../../lib/runtime-client");
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    const completed = payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      event_cursor: 3,
      revision: 7,
      route: "terminal",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockRejectedValueOnce(new runtime.RuntimeClientError("offline", "network"));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), waiting]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve exact terms" }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    const pending = runtime.loadPersistedWorkspace()?.pendingCommand;
    expect(pending?.kind).toBe("decide_approval");

    cleanup();
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok",
      ready: true,
      dependency: "postgres",
      adapter_mode: "scripted",
      storage_mode: "postgres",
      orchestration_mode: "temporal",
      error_category: "none",
    });
    vi.mocked(runtime.decideApproval).mockReset().mockResolvedValue(completed);
    vi.mocked(runtime.getCase).mockReset()
      .mockResolvedValueOnce(waiting)
      .mockResolvedValueOnce(completed);
    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    expect(vi.mocked(runtime.getCase).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(runtime.decideApproval).mock.invocationCallOrder[0] ?? Infinity,
    );
    expect(vi.mocked(runtime.decideApproval).mock.calls).toHaveLength(1);
    expect(vi.mocked(runtime.decideApproval).mock.calls[0]).toEqual([
      pending?.caseId,
      pending?.approvalId,
      {
        expectedActionIntentRevision: pending?.requestBody.expected_action_intent_revision,
        expectedCaseRevision: pending?.requestBody.expected_case_revision,
        expectedRevision: pending?.requestBody.expected_revision,
      },
      { idempotencyKey: pending?.idempotencyKey },
    ]);
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("reads before replaying an already-applied event and sends no duplicate POST", async () => {
    const runtime = await import("../../lib/runtime-client");
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    runtime.savePersistedWorkspace({
      schemaVersion: 1,
      caseId: payload().case_id,
      confirmedFacts: {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      pendingCommand: {
        kind: "append_event",
        idempotencyKey: "22222222-2222-4222-8222-222222222222",
        requestBody: {
          content: "Keep mobile hotspot and device financing unchanged.",
          event_type: "consumer_message",
          expected_revision: 2,
        },
        caseId: payload().case_id,
        expectedRevision: 2,
        approvalId: null,
        expectedCaseRevision: null,
        expectedActionIntentRevision: null,
      },
    });
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    vi.mocked(runtime.getCase).mockResolvedValue(waiting);
    vi.mocked(runtime.appendConsumerEvent).mockReset();

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledWith(payload().case_id);
    expect(runtime.appendConsumerEvent).not.toHaveBeenCalled();
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("reads before replaying an already-applied approval and sends no duplicate POST", async () => {
    const runtime = await import("../../lib/runtime-client");
    const completed = payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      event_cursor: 3,
      revision: 7,
      route: "terminal",
    });
    runtime.savePersistedWorkspace({
      schemaVersion: 1,
      caseId: payload().case_id,
      confirmedFacts: {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      pendingCommand: {
        kind: "decide_approval",
        idempotencyKey: "33333333-3333-4333-8333-333333333333",
        requestBody: {
          decision: "approved",
          expected_action_intent_revision: 1,
          expected_case_revision: 2,
          expected_revision: 4,
        },
        caseId: payload().case_id,
        expectedRevision: 4,
        approvalId: "22222222-2222-4222-8222-222222222222",
        expectedCaseRevision: 2,
        expectedActionIntentRevision: 1,
      },
    });
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    vi.mocked(runtime.getCase).mockResolvedValue(completed);
    vi.mocked(runtime.decideApproval).mockReset();

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledWith(payload().case_id);
    expect(runtime.decideApproval).not.toHaveBeenCalled();
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("surfaces a recoverable poll failure and reconnects to completion", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    const completed = payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      event_cursor: 3,
      revision: 7,
      route: "terminal",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockResolvedValueOnce(finalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();

    vi.mocked(runtime.getCase).mockRejectedValueOnce(new runtime.RuntimeClientError("offline", "network"));
    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect and read Case" })).toBeInTheDocument();
    expect(runtime.loadPersistedWorkspace()?.pendingCommand?.kind).toBe("append_event");

    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    vi.mocked(runtime.getCase).mockResolvedValue(completed);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("pauses unresolved polling while hidden and resumes on visibility", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    runtime.savePersistedWorkspace({
      schemaVersion: 1,
      caseId: payload().case_id,
      confirmedFacts: {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      pendingCommand: null,
    });
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    vi.mocked(runtime.getCase).mockResolvedValue(finalizing);
    vi.useFakeTimers();
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });

    render(<ConversationWorkspace />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
    });
    expect(runtime.getCase).toHaveBeenCalledTimes(1);

    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    fireEvent(document, new Event("visibilitychange"));
    await act(async () => {
      await Promise.resolve();
      vi.advanceTimersByTime(1499);
      await Promise.resolve();
    });
    expect(runtime.getCase).toHaveBeenCalledTimes(1);
    await act(async () => {
      vi.advanceTimersByTime(1);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
  });

  it("shows recoverable finalizing state for authoritative pending execution", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), finalizing]);
    vi.mocked(runtime.getCase).mockResolvedValue(finalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();
    expect(screen.getAllByText("Finalizing").length).toBeGreaterThan(0);
  });

  it("shows expired only after an authoritative expired Case read", async () => {
    const runtime = await import("../../lib/runtime-client");
    const expired = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "expired",
        expires_at: "2026-08-25T00:00:00Z",
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 5,
      route: "fast_now",
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(expired);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload(), expired]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Approval expired")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
  });

  it("bounds local deadline reads until the Runtime authoritatively expires approval", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pending = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: "2026-08-25T00:00:00Z",
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    const expired = payload({
      ...pending,
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "expired",
        expires_at: "2026-08-25T00:00:00Z",
        material_terms_hash: "hash-1",
      },
      event_cursor: 3,
      revision: 5,
    });
    const pendingAgain = { ...pending, snapshot: { ...pending.snapshot } };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);
    await completeLocalIntake(false, "yes", true, []);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset()
      .mockResolvedValueOnce(pending)
      .mockResolvedValueOnce(pendingAgain)
      .mockResolvedValueOnce(expired);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await act(async () => {
      for (let index = 0; index < 10; index += 1) await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(vi.mocked(runtime.getCase).mock.calls).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("button", { name: "Approval deadline reached" })).toBeDisabled();
    expect(vi.mocked(runtime.getCase).mock.calls).toHaveLength(2);

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.queryByText("Approval expired")).not.toBeInTheDocument();
    expect(vi.mocked(runtime.getCase).mock.calls).toHaveLength(2);

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Approval expired")).toBeInTheDocument();
    expect(vi.mocked(runtime.getCase).mock.calls).toHaveLength(3);
  });

  it("ignores an equal-revision Case response with a lower event cursor", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    const stale = { ...finalizing, event_cursor: 1 };
    const pendingPoll = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, "yes", true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockResolvedValueOnce(finalizing).mockReturnValueOnce(pendingPoll.promise);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
    });
    await act(async () => {
      pendingPoll.resolve(stale);
      await pendingPoll.promise;
    });
    expect(screen.getByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
