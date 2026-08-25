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

function payload(overrides: Partial<RuntimePayload> = {}): RuntimePayload {
  return {
    approval: null,
    case: {},
    case_id: "11111111-1111-4111-8111-111111111111",
    completion: { decision: "not_done", evidence_ids: [] },
    event_cursor: 1,
    evidence: [],
    execution_count: 0,
    revision: 2,
    route: "slow_refresh",
    snapshot: {
      case: {
        bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" }, usage: {} },
        goal: {
          forbidden_changes: ["device_financing_change"],
          required_features: ["mobile_hotspot"],
          target_monthly_total: { amount_minor: 7500, currency: "USD" },
        },
      },
      offers: [offer],
    },
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

beforeEach(() => {
  vi.clearAllMocks();
});

vi.mock("../../lib/runtime-client", async () => {
  const actual = await vi.importActual<typeof import("../../lib/runtime-client")>("../../lib/runtime-client");
  return { ...actual, appendConsumerEvent: vi.fn(), createCase: vi.fn(), decideApproval: vi.fn() };
});

describe("ConversationWorkspace", () => {
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

  it("keeps the conversation primary and completes only through the Runtime flow", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: "2026-08-25T13:00:00Z",
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    }));
    vi.mocked(runtime.decideApproval).mockResolvedValue(payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      revision: 7,
      route: "terminal",
    }));

    render(<ConversationWorkspace />);
    await waitFor(() => expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled());

    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    expect(await screen.findByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument();

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
    );
  });

  it("does not render success for a terminal payload whose evidence does not match", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: "2026-08-25T13:00:00Z",
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    }));
    vi.mocked(runtime.decideApproval).mockResolvedValue(payload({
      completion: { decision: "complete", evidence_ids: ["missing"] },
      execution_count: 1,
      route: "terminal",
    }));

    render(<ConversationWorkspace />);
    await waitFor(() => expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.click(await screen.findByRole("button", { name: /Keep both unchanged/ }));
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
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(runtime.appendConsumerEvent).not.toHaveBeenCalled();
  });

  it("blocks an incomplete pending offer without rendering an approval button", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(payload({
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
    }));

    render(<ConversationWorkspace />);
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.click(await screen.findByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("blocks a pending offer when its event response loses the Task Brief", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: "2026-08-25T13:00:00Z",
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
      snapshot: {
        case: { bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" } } },
        offers: [offer],
      },
    }));

    render(<ConversationWorkspace />);
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    fireEvent.click(await screen.findByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("ignores a create response that resolves after restart", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingCreate = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockReturnValue(pendingCreate.promise);

    render(<ConversationWorkspace />);
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
    await screen.findByText(/I'll create a local Case now/);
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
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: "2026-08-25T13:00:00Z",
        material_terms_hash: "hash-1",
      },
      revision: 4,
      route: "wait_for_approval",
    }));
    vi.mocked(runtime.decideApproval).mockReturnValue(pendingApproval.promise);

    render(<ConversationWorkspace />);
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "Lower my mobile bill" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
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
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
