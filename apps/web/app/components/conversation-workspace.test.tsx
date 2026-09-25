import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationWorkspace, isSupportedMobileBillIntent } from "./conversation-workspace";
// Real `propose_intake` outputs, pinned by tests/integration/test_stateless_intake.py.
import OFF_TOPIC_PROPOSALS from "./intake-offtopic-proposals.json";
import type { IntakeProposal, RuntimePayload } from "../../lib/runtime-client";

const offer = {
  features: ["mobile_hotspot", "unlimited_talk_text"],
  monthly_price: { amount_minor: 7200, currency: "USD" },
  provider_id: "fictional_mobile_provider",
  term_months: 1,
};

const caseRecord = {
  bill_snapshot: { monthly_total: { amount_minor: 9200, currency: "USD" } },
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

// PR-12: the free-text request and the typed proposal the Runtime returns for it.
const REQUEST_MARKER = "zebra-marker-4471";
const FULL_REQUEST = `My mobile bill is $92, get it under $75, keep my hotspot and never change device financing. ${REQUEST_MARKER}`;

function intakeProposal(
  proposal: Partial<IntakeProposal["proposal"]> = {},
  clarifications: IntakeProposal["clarifications"] = [],
): IntakeProposal {
  return {
    parser: "intake-parser-v1",
    proposal: {
      current_monthly_total: { amount_minor: 9200, currency: "USD" },
      target_monthly_total: { amount_minor: 7500, currency: "USD" },
      mobile_hotspot_required: true,
      device_financing_change_forbidden: true,
      ...proposal,
    },
    clarifications,
  };
}

const FULL_PROPOSAL = intakeProposal();
const EMPTY_PROPOSAL = intakeProposal(
  {
    current_monthly_total: null,
    target_monthly_total: null,
    mobile_hotspot_required: null,
    device_financing_change_forbidden: null,
  },
  [
    { field: "current_monthly_total", reason: "missing" },
    { field: "target_monthly_total", reason: "missing" },
    { field: "mobile_hotspot_required", reason: "missing" },
    { field: "device_financing_change_forbidden", reason: "missing" },
  ],
);

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
    proposeIntake: vi.fn(),
  };
});

describe("ConversationWorkspace", () => {
  function send(text: string) {
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));
  }

  // PR-12: one free-text request opens the Draft Task Brief card filled from
  // the (mocked) stateless intake proposal; "Create fictional Case" confirms it.
  async function completeLocalIntake(
    create = true,
    authoritativeResponses: RuntimePayload[] = [payload()],
    proposal: IntakeProposal = FULL_PROPOSAL,
  ) {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.getCase).mockReset();
    authoritativeResponses.forEach((response) => vi.mocked(runtime.getCase).mockResolvedValueOnce(response));
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(proposal);
    send(FULL_REQUEST);
    const createButton = await screen.findByRole("button", { name: "Create fictional Case" });
    if (proposal.clarifications.length === 0) expect(createButton).toBeEnabled();
    if (create) {
      fireEvent.click(createButton);
      await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
    }
  }

  async function openEmptyCard() {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(EMPTY_PROPOSAL);
    send("Lower my mobile bill");
    await screen.findByRole("heading", { name: "Confirm the facts before creating a Case." });
  }

  it.each([
    "Help me plan a vacation",
    "What is my phone price?",
    "my mobile cost increased",
  ])("keeps unsupported initial request %s off the card and does not create a Case", async (text) => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockClear();
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(EMPTY_PROPOSAL);

    render(<ConversationWorkspace />);
    const composer = screen.getByPlaceholderText("Message ProxyLoop");
    fireEvent.change(composer, { target: { value: text } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(await screen.findByText(/only supports lowering a fictional mobile bill/)).toBeInTheDocument();
    expect(runtime.proposeIntake).toHaveBeenCalledWith(text);
    expect(runtime.createCase).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Confirm the facts before creating a Case." })).not.toBeInTheDocument();
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
    expect(screen.getByRole("alert")).toHaveTextContent(/stay above the target/);
    expect(createButton).toBeDisabled();
    expect(screen.getByText("Current monthly total").nextElementSibling).toHaveTextContent("$92.00");
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

  it("PR-12: one request fills all four facts and only the create click sends them", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(false);

    expect(runtime.proposeIntake).toHaveBeenCalledTimes(1);
    expect(runtime.proposeIntake).toHaveBeenCalledWith(FULL_REQUEST);
    expect(screen.getByText(/I read all four facts from your request/)).toBeInTheDocument();
    expect(screen.getByText("Current monthly total").nextElementSibling).toHaveTextContent("$92.00 · Read from your message");
    expect(screen.getByText("Target monthly total").nextElementSibling).toHaveTextContent("$75.00 · Read from your message");
    expect(screen.getByText("Mobile hotspot required").nextElementSibling).toHaveTextContent("Required · Read from your message");
    expect(screen.getByText("Device financing change forbidden").nextElementSibling).toHaveTextContent("Unchanged · Read from your message");
    // Review I-1: a value read from the message is never labelled confirmed.
    expect(screen.queryByText(/Confirmed/)).not.toBeInTheDocument();
    expect(screen.queryByText("Missing")).not.toBeInTheDocument();
    expect(runtime.createCase).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument());
    expect(runtime.createCase).toHaveBeenCalledTimes(1);
    expect(runtime.createCase).toHaveBeenCalledWith(
      {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      { idempotencyKey: expect.any(String) },
    );
  });

  it("PR-12: a partial proposal asks only for the missing fact", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { target_monthly_total: null },
      [{ field: "target_monthly_total", reason: "missing" }],
    ));

    expect(screen.getByText(/What monthly total would you like to reach/)).toBeInTheDocument();
    expect(screen.queryByText(/What is your current monthly bill total/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Missing")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();

    send("$75");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await waitFor(() => expect(runtime.createCase).toHaveBeenCalledWith(
      expect.objectContaining({ targetMonthlyTotal: { amount_minor: 7500, currency: "USD" } }),
      { idempotencyKey: expect.any(String) },
    ));
  });

  it.each([
    [
      "ambiguous",
      intakeProposal({ target_monthly_total: null }, [{ field: "target_monthly_total", reason: "ambiguous" }]),
      "Needs clarification · more than one reading",
    ],
    [
      "invalid_amount",
      intakeProposal({ target_monthly_total: null }, [{ field: "target_monthly_total", reason: "invalid_amount" }]),
      "Needs clarification · not a valid USD amount",
    ],
    [
      "below_fixed_offer",
      intakeProposal(
        { target_monthly_total: { amount_minor: 7000, currency: "USD" } },
        [{ field: "target_monthly_total", reason: "below_fixed_offer" }],
      ),
      "$70.00 · Read from your message · below the $72.00 fictional offer",
    ],
  ])("PR-12: a %s target shows its clarification and blocks Create until answered", async (_reason, proposal, shown) => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], proposal);

    expect(screen.getByText("Target monthly total").nextElementSibling).toHaveTextContent(shown);
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();

    send("$75");
    expect(screen.getByText("Target monthly total").nextElementSibling).toHaveTextContent("$75.00");
    expect(screen.getByText("Target monthly total").nextElementSibling).not.toHaveTextContent("Needs clarification");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("PR-12: unsupported currency on both amounts asks for each in turn", async () => {
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { current_monthly_total: null, target_monthly_total: null },
      [
        { field: "current_monthly_total", reason: "unsupported_currency" },
        { field: "target_monthly_total", reason: "unsupported_currency" },
      ],
    ));

    expect(screen.getAllByText("Needs clarification · USD only")).toHaveLength(2);
    send("$92");
    send("$75");
    expect(screen.queryByText(/Needs clarification/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
  });

  it("PR-12: an ambiguous financing fact needs an unambiguous confirmation", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { device_financing_change_forbidden: null },
      [{ field: "device_financing_change_forbidden", reason: "ambiguous" }],
    ));
    expect(screen.getByText(/Should device financing remain unchanged/)).toBeInTheDocument();

    send("no change, but I want to change device financing");
    expect(screen.getByRole("alert")).toHaveTextContent(/Device financing must remain unchanged/);
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    send("no change, but please modify device financing");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();

    send("no change");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await waitFor(() => expect(runtime.createCase).toHaveBeenCalledWith(
      expect.objectContaining({ deviceFinancingChangeForbidden: true }),
      { idempotencyKey: expect.any(String) },
    ));
  });

  it("PR-12: an ambiguous hotspot fact rejects contradictory confirmation locally", async () => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { mobile_hotspot_required: null },
      [{ field: "mobile_hotspot_required", reason: "ambiguous" }],
    ));

    send("yes, remove mobile hotspot");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(/Mobile hotspot must remain required/);
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  // Fourth amendment M-5: every non-success path of the intake proposal gets
  // the same intake copy, through the real client and a stubbed fetch.
  const INTAKE_FAILURE_COPY = "I couldn't read that message right now. Nothing was created.";
  const jsonResponse = (status: number, body: unknown) =>
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  it.each([
    ["422", () => jsonResponse(422, { detail: { code: "request_invalid", message: "request rejected" } })],
    ["404", () => jsonResponse(404, { detail: "Not Found" })],
    ["409", () => jsonResponse(409, { detail: { code: "conflict", message: "conflict" } })],
    ["500", () => jsonResponse(500, { detail: { code: "internal_error", message: "internal error" } })],
    ["503", () => new Response("upstream unavailable", { status: 503 })],
    ["network", () => { throw new TypeError("fetch failed"); }],
    ["200 non-JSON body", () => new Response("<html>ok</html>", { status: 200 })],
    ["200 invalid proposal", () => jsonResponse(200, { ...EMPTY_PROPOSAL, extra: true })],
  ] as const)("PR-12 M-5: a %s proposal failure gets the intake copy and creates nothing", async (_kind, respond) => {
    const runtime = await import("../../lib/runtime-client");
    const actual = await vi.importActual<typeof import("../../lib/runtime-client")>("../../lib/runtime-client");
    const fetchStub = vi.fn(async () => respond());
    vi.stubGlobal("fetch", fetchStub);
    vi.mocked(runtime.proposeIntake).mockReset().mockImplementation(actual.proposeIntake);
    vi.mocked(runtime.createCase).mockClear();
    try {
      render(<ConversationWorkspace />);

      send(FULL_REQUEST);

      expect(await screen.findByText(INTAKE_FAILURE_COPY)).toBeInTheDocument();
      expect(fetchStub).toHaveBeenCalledTimes(1);
      expect(screen.queryByText(/Nothing was created\..*Nothing was created/)).not.toBeInTheDocument();
      expect(screen.queryByText(/could not be reached|rejected this state|could not read that request/)).not.toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Confirm the facts before creating a Case." })).not.toBeInTheDocument();
      expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled();
      expect(runtime.createCase).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("PR-12 I-1: a fact the consumer supplies is shown as confirmed; the others stay read", async () => {
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { mobile_hotspot_required: null },
      [{ field: "mobile_hotspot_required", reason: "ambiguous" }],
    ));

    send("yes");
    expect(screen.getByText("Mobile hotspot required").nextElementSibling).toHaveTextContent("Confirmed · required");
    expect(screen.getByText("Mobile hotspot required").nextElementSibling).not.toHaveTextContent("Read from your message");
    expect(screen.getByText("Device financing change forbidden").nextElementSibling).toHaveTextContent("Unchanged · Read from your message");
  });

  it("PR-12 I-3: editing the current bill re-prompts a target that still breaks its rule", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { target_monthly_total: { amount_minor: 7000, currency: "USD" } },
      [{ field: "target_monthly_total", reason: "below_fixed_offer" }],
    ));

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    send("$95");

    expect(screen.getByText("Current monthly total").nextElementSibling).toHaveTextContent("$95.00");
    expect(screen.getByText("Target monthly total").nextElementSibling).toHaveTextContent("below the $72.00 fictional offer");
    expect(screen.getAllByText(/What monthly total would you like to reach/).length).toBeGreaterThan(1);
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();

    send("$80");
    expect(screen.getByText("Target monthly total").nextElementSibling).not.toHaveTextContent("below the $72.00");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await waitFor(() => expect(runtime.createCase).toHaveBeenCalledWith(
      expect.objectContaining({
        currentMonthlyTotal: { amount_minor: 9500, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 8000, currency: "USD" },
      }),
      { idempotencyKey: expect.any(String) },
    ));
  });

  it("PR-12 I-3: a target_not_below_current target is released once the current bill is raised", async () => {
    render(<ConversationWorkspace />);
    await completeLocalIntake(false, [payload()], intakeProposal(
      { current_monthly_total: { amount_minor: 8000, currency: "USD" }, target_monthly_total: { amount_minor: 8500, currency: "USD" } },
      [{ field: "target_monthly_total", reason: "target_not_below_current" }],
    ));

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    send("$92");

    expect(screen.getByText("Target monthly total").nextElementSibling).not.toHaveTextContent("must stay below");
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeEnabled();
  });

  it("PR-12 M-3: an amount above $999,999.99 is refused locally", async () => {
    render(<ConversationWorkspace />);
    await openEmptyCard();

    send("$1,000,000");

    expect(screen.getByRole("alert")).toHaveTextContent("Amounts above $999,999.99 are not supported.");
    expect(screen.getAllByText("Missing")).toHaveLength(4);
  });

  // Real parser outputs. The card opens on a read value, on the scope gate, or
  // on an amount clarification with a bill or payment cue (third amendment);
  // otherwise the scope reply. Bare "plan" is not a cue (documented limit).
  it.each([
    ["Help me plan a vacation for $2,000", false],
    ["What does device financing mean?", false],
    ["Can I keep my hotspot?", false],
    ["Convert 10 euros to dollars", false],
    ["Write me a poem about my $5 coffee", false],
    ["My bill is $92 and I'd like $75", true],
    ["My bill went up to $92 and I want $80", true],
    ["My plan went up to $92", false],
    ["Which phone should I take on a euro trip?", false],
  ] as const)("PR-12 M-1: the real proposal for %s opens the card: %s", async (text, opensCard) => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(
      OFF_TOPIC_PROPOSALS[text] as IntakeProposal,
    );
    render(<ConversationWorkspace />);

    send(text);

    if (opensCard) {
      expect(await screen.findByRole("heading", { name: "Confirm the facts before creating a Case." })).toBeInTheDocument();
      expect(screen.queryByText(/only supports lowering a fictional mobile bill/)).not.toBeInTheDocument();
    } else {
      expect(await screen.findByText(/only supports lowering a fictional mobile bill/)).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Confirm the facts before creating a Case." })).not.toBeInTheDocument();
    }
  });

  // Third amendment: an amount clarification opens the card only with a cue
  // from the closed list, matched as a whole word or phrase.
  it.each([
    ["My bill went up to $92", true],
    ["I pay $92, maybe $80", true],
    ["I'm paying $92, maybe $80", true],
    ["I paid $92, maybe $80", true],
    ["It is $92 monthly, maybe $80", true],
    ["It is $92 per month, maybe $80", true],
    ["It is $92 a month, maybe $80", true],
    ["It is $92/mo, maybe $80", true],
    ["My carrier went up to $92", true],
    ["My phone went up to $92", true],
    ["Mobile went up to $92", true],
    ["Cell went up to $92", true],
    ["Wireless went up to $92", true],
    ["Data went up to $92", true],
    ["Hotspot went up to $92", true],
    ["Financing went up to $92", true],
    ["My plan went up to $92", false],
    ["My billfold holds $92", false],
    ["I spent $92 on a payment app, maybe $80", false],
    ["Twelve months ago it was $92, maybe $80", false],
    ["The database cost $92, maybe $80", false],
  ] as const)("PR-12 third amendment: an unsure amount in %s opens the card: %s", async (text, opensCard) => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(intakeProposal(
      { current_monthly_total: null, target_monthly_total: null, mobile_hotspot_required: null, device_financing_change_forbidden: null },
      [
        { field: "current_monthly_total", reason: "ambiguous" },
        { field: "target_monthly_total", reason: "ambiguous" },
        { field: "mobile_hotspot_required", reason: "missing" },
        { field: "device_financing_change_forbidden", reason: "missing" },
      ],
    ));
    render(<ConversationWorkspace />);

    send(text);

    if (opensCard) {
      expect(await screen.findByRole("heading", { name: "Confirm the facts before creating a Case." })).toBeInTheDocument();
    } else {
      expect(await screen.findByText(/only supports lowering a fictional mobile bill/)).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Confirm the facts before creating a Case." })).not.toBeInTheDocument();
    }
  });

  it("PR-12 re-review: on-topic text with an unsure amount and no phone word opens the card", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.proposeIntake).mockReset().mockResolvedValue(intakeProposal(
      { current_monthly_total: null, target_monthly_total: null, mobile_hotspot_required: null, device_financing_change_forbidden: null },
      [
        { field: "current_monthly_total", reason: "ambiguous" },
        { field: "target_monthly_total", reason: "ambiguous" },
        { field: "mobile_hotspot_required", reason: "missing" },
        { field: "device_financing_change_forbidden", reason: "missing" },
      ],
    ));
    render(<ConversationWorkspace />);

    send("I pay $92 and I'd rather pay $75 or maybe $78");

    expect(await screen.findByRole("heading", { name: "Confirm the facts before creating a Case." })).toBeInTheDocument();
    expect(screen.getAllByText("Needs clarification · more than one reading")).toHaveLength(2);
  });

  it("PR-12 M-6: a proposal that resolves after Restart opens no card", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pending = deferred<IntakeProposal>();
    vi.mocked(runtime.proposeIntake).mockReset().mockReturnValue(pending.promise);
    render(<ConversationWorkspace />);

    send(FULL_REQUEST);
    fireEvent.click(screen.getByRole("button", { name: /New task/ }));
    await act(async () => {
      pending.resolve(FULL_PROPOSAL);
      await pending.promise;
    });

    expect(screen.queryByRole("heading", { name: "Confirm the facts before creating a Case." })).not.toBeInTheDocument();
    expect(screen.queryByText(/I read all four facts/)).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled();
  });

  it("PR-12: refuses an over-long request locally without calling the Runtime", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.proposeIntake).mockReset();
    render(<ConversationWorkspace />);

    send(`Lower my mobile bill ${"x".repeat(2000)}`);

    expect(screen.getByText(/Please keep the request under 2,000 characters/)).toBeInTheDocument();
    expect(runtime.proposeIntake).not.toHaveBeenCalled();
  });

  it("PR-12: the request text is never stored in the browser envelope", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload());
    render(<ConversationWorkspace />);
    await completeLocalIntake(true);

    const stored = Object.keys(window.localStorage).map((key) => window.localStorage.getItem(key) ?? "").join("\n");
    expect(stored).toContain("currentMonthlyTotal");
    expect(stored).not.toContain(REQUEST_MARKER);
    expect(stored).not.toContain("never change device financing");
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
    await completeLocalIntake(true, [payload(), waiting, completed]);

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
    await completeLocalIntake(true, [payload(), waiting, invalidCompleted]);
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
    await completeLocalIntake(true, [payload(), incomplete]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it.each([
    [
      "an incomplete pending approval read back from the Case",
      payload({
        approval: {
          action_intent_revision: 1,
          approval_id: "22222222-2222-4222-8222-222222222222",
          case_revision: 2,
          decision: "pending",
        },
        revision: 4,
        route: "wait_for_approval",
      }),
    ],
    [
      "an event response that drifts an intake fact",
      payload({
        revision: 4,
        snapshot: {
          case: { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } },
          offers: [offer],
        },
      }),
    ],
  ])("R6: %s is terminal Blocked with no confirm or approval action and no second event", async (_label, blocked) => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(blocked);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockResolvedValue(blocked);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(screen.queryByText("Needs input")).not.toBeInTheDocument();
    const confirm = document.getElementById("task-brief-confirm");
    expect(confirm).toBeDisabled();
    expect(confirm).toHaveTextContent("Blocked");
    fireEvent.click(confirm as HTMLElement);
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("R7: a create response that mismatches the confirmed draft is terminal Blocked with no second create", async () => {
    const runtime = await import("../../lib/runtime-client");
    const driftedCase = { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } };
    vi.mocked(runtime.createCase).mockReset().mockResolvedValue(payload({
      case: driftedCase,
      snapshot: { case: driftedCase, offers: [offer] },
    }));

    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create fictional Case" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(runtime.createCase).toHaveBeenCalledTimes(1);
    expect(runtime.getCase).not.toHaveBeenCalled();
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
    await completeLocalIntake(true, [payload(), lostBrief]);
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
    await completeLocalIntake(true, [payload(), drifted]);
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
    await completeLocalIntake(true, [payload(), waiting]);
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
    await completeLocalIntake(true, [payload()]);
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
    await completeLocalIntake(true, [payload(), waiting]);
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
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockResolvedValueOnce(finalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();

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
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
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
    await completeLocalIntake(true, [payload(), finalizing]);
    vi.mocked(runtime.getCase).mockResolvedValue(finalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
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
    await completeLocalIntake(true, [payload(), expired]);
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
    await completeLocalIntake(false, []);
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
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockResolvedValueOnce(finalizing).mockReturnValueOnce(pendingPoll.promise);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
    });
    await act(async () => {
      pendingPoll.resolve(stale);
      await pendingPoll.promise;
    });
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
  });

  it("surfaces a 409 on the constraint event when the reconcile read does not advance the revision", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockRejectedValueOnce(new runtime.RuntimeClientError(
      "The Runtime refused this turn (category: model_result_rejected). Reconnect and read the Case, or restart the demo.",
      "http",
      409,
      "model_result_rejected",
    ));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockResolvedValue(payload());
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("model_result_rejected");
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(document.getElementById("task-brief-confirm")).toBeDisabled();
    expect(document.getElementById("task-brief-confirm")).toHaveTextContent("Reconnect to continue");
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();

    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
    expect(await screen.findByRole("button", { name: /Keep both unchanged/ })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledTimes(3);
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("keeps the constraint button and the exact retry after a transient non-409 failure", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockRejectedValueOnce(new runtime.RuntimeClientError(
      "The local Runtime request failed safely. Reconnect and retry when ready.",
      "network",
    ));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("failed safely");
    const stored = runtime.loadPersistedWorkspace()?.pendingCommand;
    expect(stored?.kind).toBe("append_event");
    // A transient failure is not a dropped retry: the primary action stays
    // available and re-sends the exact same command.
    const button = await screen.findByRole("button", { name: /Keep both unchanged/ });
    expect(button).toBeEnabled();
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValueOnce(payload({ revision: 2 }));
    fireEvent.click(button);
    await waitFor(() => expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(2));
    expect(vi.mocked(runtime.appendConsumerEvent).mock.calls[1]).toEqual([
      stored?.caseId,
      stored?.requestBody.content,
      stored?.expectedRevision,
      { idempotencyKey: stored?.idempotencyKey },
    ]);
  });

  it("surfaces an explicit still-waiting error with reconnect after five finalizing reads", async () => {
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
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...finalizing }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
      for (let i = 0; i < 6; i += 1) await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
    const readsBeforePolling = vi.mocked(runtime.getCase).mock.calls.length;

    for (let poll = 0; poll < 8; poll += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1500);
        for (let i = 0; i < 4; i += 1) await Promise.resolve();
      });
    }
    expect(vi.mocked(runtime.getCase).mock.calls.length - readsBeforePolling).toBe(5);
    expect(screen.getByRole("alert")).toHaveTextContent("Still waiting for the authoritative result after 5 reads");
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();

    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
      for (let i = 0; i < 6; i += 1) await Promise.resolve();
    });
    // Reconnect reads the Case (6th read), then replays the kept exact
    // append_event retry and reads once more after it.
    expect(vi.mocked(runtime.getCase).mock.calls.length - readsBeforePolling).toBe(7);
    expect(vi.mocked(runtime.appendConsumerEvent).mock.calls).toHaveLength(2);
    expect(vi.mocked(runtime.appendConsumerEvent).mock.calls[1]?.[3]).toEqual(
      vi.mocked(runtime.appendConsumerEvent).mock.calls[0]?.[3],
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
  });

  it("keeps and replays the exact pending approval while the approved execution is still pending", async () => {
    const runtime = await import("../../lib/runtime-client");
    const claimed = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "approved",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 3,
      revision: 5,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    const completed = payload({
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      event_cursor: 4,
      revision: 7,
      route: "terminal",
    });
    const stored = {
      kind: "decide_approval" as const,
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
    };
    runtime.savePersistedWorkspace({
      schemaVersion: 1,
      caseId: payload().case_id,
      confirmedFacts: {
        currentMonthlyTotal: { amount_minor: 9200, currency: "USD" },
        targetMonthlyTotal: { amount_minor: 7500, currency: "USD" },
        mobileHotspotRequired: true,
        deviceFinancingChangeForbidden: true,
      },
      pendingCommand: stored,
    });
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "ok", ready: true, dependency: "postgres", adapter_mode: "scripted",
      storage_mode: "postgres", orchestration_mode: "temporal", error_category: "none",
    });
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...claimed }));
    vi.mocked(runtime.decideApproval).mockReset().mockResolvedValue(claimed);
    vi.useFakeTimers();

    render(<ConversationWorkspace />);
    await act(async () => {
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();
    expect(vi.mocked(runtime.decideApproval).mock.calls).toHaveLength(1);
    expect(vi.mocked(runtime.decideApproval).mock.calls[0]).toEqual([
      stored.caseId,
      stored.approvalId,
      {
        expectedActionIntentRevision: stored.requestBody.expected_action_intent_revision,
        expectedCaseRevision: stored.requestBody.expected_case_revision,
        expectedRevision: stored.requestBody.expected_revision,
      },
      { idempotencyKey: stored.idempotencyKey },
    ]);
    expect(runtime.loadPersistedWorkspace()?.pendingCommand?.idempotencyKey).toBe(stored.idempotencyKey);

    vi.mocked(runtime.getCase).mockResolvedValue(completed);
    await act(async () => {
      vi.advanceTimersByTime(1500);
      for (let i = 0; i < 4; i += 1) await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    expect(vi.mocked(runtime.decideApproval).mock.calls).toHaveLength(1);
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it.each([
    "12.345",
    "$12.345",
    "-5",
    "-$5",
    "$-5",
    "1e3",
    "$1e3",
    "$",
    "€92",
    "92 EUR",
    "£92",
    "$92 or $95",
  ])("rejects the non-strict USD input %s locally", async (input) => {
    const runtime = await import("../../lib/runtime-client");
    render(<ConversationWorkspace />);
    await openEmptyCard();
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: input } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Use one non-negative USD value such as $92.00.");
    expect(screen.getAllByText("Missing")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Create fictional Case" })).toBeDisabled();
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("cannot submit an empty USD input", async () => {
    render(<ConversationWorkspace />);
    await openEmptyCard();
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: "   " } });

    expect(screen.getByRole("button", { name: "Send message" })).toBeDisabled();
    expect(screen.getAllByText("Missing")).toHaveLength(4);
  });

  it("keeps the exact event retry and truthful copy on temporal_unavailable", async () => {
    const runtime = await import("../../lib/runtime-client");
    const copy = "The local orchestration attempt is still unresolved. Your Case and safe retry remain preserved; reconnect to read authoritative state.";
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset()
      .mockRejectedValueOnce(new runtime.RuntimeClientError(copy, "http", 503, "temporal_unavailable"));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
    expect(screen.queryAllByText("Blocked")).toHaveLength(0);
    expect(screen.getByRole("button", { name: /Keep both unchanged/ })).toBeEnabled();
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toMatchObject({
      kind: "append_event",
      idempotencyKey: vi.mocked(runtime.appendConsumerEvent).mock.calls[0]?.[3]?.idempotencyKey,
    });
  });

  it("preserves the saved Case and pending command when readiness reports ready:false", async () => {
    const runtime = await import("../../lib/runtime-client");
    const stored = storedWorkspace(storedPendingEvent);
    runtime.savePersistedWorkspace(stored);
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      status: "unavailable",
      ready: false,
      dependency: "runtime",
      error_category: "temporal_unavailable",
    });
    vi.mocked(runtime.getCase).mockReset();
    vi.mocked(runtime.appendConsumerEvent).mockReset();

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The local Runtime is not ready yet. Your saved Case and pending command remain preserved.",
    );
    expect(runtime.getCase).not.toHaveBeenCalled();
    expect(runtime.appendConsumerEvent).not.toHaveBeenCalled();
    expect(runtime.loadPersistedWorkspace()).toEqual(stored);
    expect(screen.getByRole("button", { name: "Reconnect and read Case" })).toBeInTheDocument();
  });

  it.each([
    ["no orchestration_mode", { orchestration_mode: undefined }],
    ["storage_mode memory", { storage_mode: "memory" }],
    ["direct with PostgreSQL storage", { orchestration_mode: "direct" }],
    ["adapter_mode other than scripted", { adapter_mode: "hosted" }],
    ["hosted adapter_mode model", { adapter_mode: "model" }],
    ["direct with PostgreSQL storage and local_distilled_candidate", { orchestration_mode: "direct", adapter_mode: "local_distilled_candidate" }],
    ["direct with PostgreSQL storage and local_untuned_baseline", { orchestration_mode: "direct", adapter_mode: "local_untuned_baseline" }],
  ])("makes no recovery claim against a non-durable readiness profile: %s", async (_label, change) => {
    const runtime = await import("../../lib/runtime-client");
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue({ ...DURABLE_READY, ...change });
    vi.mocked(runtime.getCase).mockReset();

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Recovery requires the durable Temporal/PostgreSQL/scripted Runtime profile. The direct Runtime makes no restart-recovery claim.",
    );
    expect(runtime.getCase).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
  });

  it.each(["local_distilled_candidate", "local_untuned_baseline"])(
    "restores a stored Case on a local Fast backend under Temporal and PostgreSQL: %s",
    async (adapterMode) => {
      const runtime = await import("../../lib/runtime-client");
      runtime.savePersistedWorkspace(storedWorkspace(null));
      vi.mocked(runtime.checkReadiness).mockResolvedValue({ ...DURABLE_READY, adapter_mode: adapterMode });
      vi.mocked(runtime.getCase).mockReset().mockResolvedValue(payload());

      render(<ConversationWorkspace />);

      expect(await screen.findByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument();
      expect(runtime.getCase).toHaveBeenCalledWith(payload().case_id);
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );

  it("names the direct one-Case limit and the Runtime restart instead of a durable-recovery block", async () => {
    const runtime = await import("../../lib/runtime-client");
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue({
      ...DURABLE_READY,
      dependency: "memory",
      storage_mode: "memory",
      orchestration_mode: "direct",
    });
    vi.mocked(runtime.getCase).mockReset();

    render(<ConversationWorkspace />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "The direct Runtime keeps one Case per Runtime process and does not resume it after a page reload. Restart the Runtime process to start over, then choose Restart local demo.",
    );
    expect(alert).not.toHaveTextContent("Recovery requires the durable");
    expect(runtime.getCase).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
  });

  it("shows the bounded reset message and invents no Case on a restore 404", async () => {
    const runtime = await import("../../lib/runtime-client");
    const copy = "The saved Case is no longer available in the local Runtime. Reset this local task to continue.";
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockReset()
      .mockRejectedValue(new runtime.RuntimeClientError(copy, "http", 404, "case_not_found"));

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent(copy);
    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(runtime.createCase).not.toHaveBeenCalled();
  });

  it("shows no Task Brief when create is rejected with 422", async () => {
    const runtime = await import("../../lib/runtime-client");
    const copy = "The local Runtime rejected this state safely. No unverified result is shown.";
    vi.mocked(runtime.createCase).mockReset()
      .mockRejectedValueOnce(new runtime.RuntimeClientError(copy, "http", 422, "request_invalid"));

    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expect(screen.getByText(copy)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
    expect(runtime.getCase).not.toHaveBeenCalled();
  });

  it("discards a stale restored command with the restore-409 message", async () => {
    const runtime = await import("../../lib/runtime-client");
    runtime.savePersistedWorkspace(storedWorkspace(storedPendingEvent));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockRejectedValueOnce(new runtime.RuntimeClientError(
      "The Runtime refused this command because it conflicts with the current Case. Retry only if the action is still offered; to start over, restart the Runtime process (or reset the durable demo), then choose New task.",
      "http",
      409,
      "case_conflict",
    ));

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Runtime rejected this stale command. I read the current Case and discarded that retry.",
    );
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
    expect(runtime.loadPersistedWorkspace()?.pendingCommand).toBeNull();
  });

  it("shows Connecting while the explicit create request is in flight", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingCreate = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockReset().mockReturnValue(pendingCreate.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(false);
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));

    expect(screen.getAllByText("Connecting").length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText("Connecting to local Runtime…")).toBeDisabled();
    expect(screen.queryByRole("heading", { name: "Here is what I will work from." })).not.toBeInTheDocument();
  });

  it("suppresses a double click on confirm and shows Working while the event is in flight", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    const confirm = screen.getByRole("button", { name: /Keep both unchanged/ });
    fireEvent.click(confirm);
    fireEvent.click(confirm);

    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(screen.getAllByText("Working").length).toBeGreaterThan(0);
  });

  it("suppresses a double click on approve", async () => {
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
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReset().mockReturnValue(pendingApproval.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload(), waiting]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    const approve = await screen.findByRole("button", { name: "Approve exact terms" });
    fireEvent.click(approve);
    fireEvent.click(approve);

    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);
    expect(approve).toBeDisabled();
    expect(approve).toHaveTextContent("Sending exact approval…");
  });

  it("backs deadline reads off to 1500 ms and stops after the 5-read budget", async () => {
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
    vi.mocked(runtime.createCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);
    await completeLocalIntake(false, []);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...pending }));
    const flush = async (ms: number | null) => {
      await act(async () => {
        if (ms !== null) vi.advanceTimersByTime(ms);
        for (let index = 0; index < 10; index += 1) await Promise.resolve();
      });
    };
    fireEvent.click(screen.getByRole("button", { name: "Create fictional Case" }));
    await flush(null);
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledTimes(1);

    await flush(0);
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
    await flush(1499);
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
    await flush(1);
    expect(runtime.getCase).toHaveBeenCalledTimes(3);
    for (let read = 0; read < 3; read += 1) await flush(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(6);

    for (let idle = 0; idle < 10; idle += 1) await flush(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(6);
    expect(screen.getByRole("button", { name: "Approval deadline reached" })).toBeDisabled();
    expect(screen.queryByText("Approval expired")).not.toBeInTheDocument();
  });

  const flushMicrotasks = async (ms: number | null = null) => {
    await act(async () => {
      if (ms !== null) vi.advanceTimersByTime(ms);
      for (let index = 0; index < 10; index += 1) await Promise.resolve();
    });
  };

  function expectStickyBlocked() {
    expect(screen.getAllByText("Blocked").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve exact terms" })).not.toBeInTheDocument();
    expect(document.getElementById("task-brief-confirm")).toBeDisabled();
    expect(document.getElementById("task-brief-confirm")).toHaveTextContent("Blocked");
  }

  it("B1: a working poll that blocks stays Blocked when the in-flight event POST then fails", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    expect(screen.getAllByText("Working").length).toBeGreaterThan(0);

    await flushMicrotasks(1500);
    expectStickyBlocked();

    pendingEvent.reject(new runtime.RuntimeClientError("offline", "network"));
    await flushMicrotasks();
    expectStickyBlocked();
    fireEvent.click(document.getElementById("task-brief-confirm") as HTMLElement);
    const reads = vi.mocked(runtime.getCase).mock.calls.length;
    await flushMicrotasks(15000);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads);
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("B1 approval twin: a deadline poll that blocks stays Blocked when the in-flight approval then fails", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingApproval = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: new Date(Date.now() + 1000).toISOString(),
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReset().mockReturnValue(pendingApproval.promise);
    vi.mocked(runtime.getCase).mockReset()
      .mockResolvedValueOnce(waiting)
      .mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL, event_cursor: 3, revision: 5 }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    fireEvent.click(screen.getByRole("button", { name: "Approve exact terms" }));
    await flushMicrotasks();
    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);

    await flushMicrotasks(1000);
    expectStickyBlocked();

    pendingApproval.reject(new runtime.RuntimeClientError("offline", "network"));
    await flushMicrotasks();
    expectStickyBlocked();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;
    await flushMicrotasks(15000);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads);
    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);
  });

  it("N-1: deadline reads during an in-flight approval POST stay 1500 ms apart", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingApproval = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: new Date(Date.now() + 5000).toISOString(),
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 4,
      route: "wait_for_approval",
    });
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReset().mockReturnValue(pendingApproval.promise);
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...waiting }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    fireEvent.click(screen.getByRole("button", { name: "Approve exact terms" }));
    await flushMicrotasks();
    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);

    await flushMicrotasks(5001);
    const reads = vi.mocked(runtime.getCase).mock.calls.length;
    for (let flush = 0; flush < 30; flush += 1) await flushMicrotasks(0);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads);
    await flushMicrotasks(1499);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads);
    await flushMicrotasks(1);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 1);
  });

  it("I1: an approval response that drifts an intake fact is Blocked with no second approval", async () => {
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
    const driftedCase = { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReset().mockResolvedValue(payload({
      case: driftedCase,
      revision: 7,
      snapshot: { case: driftedCase, offers: [offer] },
    }));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload(), waiting]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve exact terms" }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expectStickyBlocked();
    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);
  });

  it("I2a: a valid event response followed by a drifted Case read is Blocked with no confirm", async () => {
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
    const driftedCase = { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [
      payload(),
      { ...waiting, case: driftedCase, snapshot: { case: driftedCase, offers: [offer] } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expectStickyBlocked();
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("I2b: a finalizing poll that reads an incomplete approval is Blocked and stops polling", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset()
      .mockResolvedValueOnce(finalizing)
      .mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL, event_cursor: 3, revision: 7 }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();

    await flushMicrotasks(1500);
    expectStickyBlocked();
    expect(screen.queryByRole("heading", { name: "Finalizing the fictional transition" })).not.toBeInTheDocument();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;
    for (let poll = 0; poll < 6; poll += 1) await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads);
  });

  it("M2: reconnect from Blocked reads again and replays no command while the Case is still blocked", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(INCOMPLETE_APPROVAL);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expectStickyBlocked();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;

    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
    await waitFor(() => expect(runtime.getCase).toHaveBeenCalledTimes(reads + 1));
    await waitFor(() => expectStickyBlocked());
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  function validPendingApproval(overrides: Partial<RuntimePayload> = {}): RuntimePayload {
    return payload({
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
      ...overrides,
    });
  }

  it("sticky I1: after a poll blocks, a late valid event response and valid reads stay Blocked", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    await flushMicrotasks(1500);
    expectStickyBlocked();

    vi.mocked(runtime.getCase).mockImplementation(async () => validPendingApproval());
    pendingEvent.resolve(validPendingApproval());
    await flushMicrotasks();
    expectStickyBlocked();
    await flushMicrotasks(15000);
    expectStickyBlocked();
    expect(screen.queryByRole("heading", { name: "Accept these exact fictional terms?" })).not.toBeInTheDocument();
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
    expect(runtime.decideApproval).not.toHaveBeenCalled();
  });

  it("sticky I2: Reconnect from Blocked to a valid Case offers approval once and replays no event", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingApproval = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(INCOMPLETE_APPROVAL);
    vi.mocked(runtime.decideApproval).mockReset().mockReturnValue(pendingApproval.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expectStickyBlocked();

    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockImplementation(async () => validPendingApproval({ event_cursor: 3, revision: 5 }));
    fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
    const approve = await screen.findByRole("button", { name: "Approve exact terms" });
    expect(approve).toBeEnabled();
    expect(screen.queryAllByText("Blocked")).toHaveLength(0);
    fireEvent.click(approve);
    fireEvent.click(approve);

    expect(runtime.decideApproval).toHaveBeenCalledTimes(1);
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("sticky I3: Restart from Blocked lets a fresh intake reach a clickable confirm", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(INCOMPLETE_APPROVAL);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...INCOMPLETE_APPROVAL }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    expectStickyBlocked();

    fireEvent.click(screen.getByRole("button", { name: "Restart local demo" }));
    await completeLocalIntake(true, [payload()]);

    expect(screen.getByRole("button", { name: /Keep both unchanged/ })).toBeEnabled();
    expect(screen.queryAllByText("Blocked")).toHaveLength(0);
    expect(runtime.createCase).toHaveBeenCalledTimes(2);
  });

  it("E-7: an unchanged poll during the in-flight event POST keeps Working instead of re-showing confirm", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
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
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => payload());
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();

    await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Working").length).toBeGreaterThan(0);
    expect(screen.queryByText("Needs input")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Waiting for the Runtime decision" })).toBeInTheDocument();
    expect(document.getElementById("task-brief-confirm")).toBeDisabled();

    vi.mocked(runtime.getCase).mockImplementation(async () => waiting);
    pendingEvent.resolve(waiting);
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("I-1: polls during a long in-flight event POST continue without exhausting the poll budget", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
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
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => payload());
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    for (let tick = 0; tick < 7; tick += 1) await flushMicrotasks(1500);

    expect(vi.mocked(runtime.getCase).mock.calls.length).toBeGreaterThan(5);
    expect(screen.queryByText(/Still waiting for the authoritative result/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reconnect and read Case" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Working").length).toBeGreaterThan(0);

    vi.mocked(runtime.getCase).mockImplementation(async () => waiting);
    pendingEvent.resolve(waiting);
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("I-1: a budget error from a stalled reconnect is cleared once its authoritative reads and replay succeed", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    const waiting = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "pending",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 3,
      revision: 7,
      route: "wait_for_approval",
    });
    const readiness = deferred<Awaited<ReturnType<typeof runtime.checkReadiness>>>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...finalizing }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    for (let tick = 0; tick < 7; tick += 1) await flushMicrotasks(1500);
    expect(screen.getByRole("alert")).toHaveTextContent("Still waiting for the authoritative result after 5 reads");

    vi.mocked(runtime.checkReadiness).mockReset().mockReturnValue(readiness.promise);
    fireEvent.click(screen.getByRole("button", { name: "Reconnect and read Case" }));
    await flushMicrotasks();
    for (let tick = 0; tick < 7; tick += 1) await flushMicrotasks(1500);
    expect(screen.getByRole("alert")).toHaveTextContent("Still waiting for the authoritative result after 5 reads");

    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...waiting }));
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(waiting);
    readiness.resolve(DURABLE_READY as Awaited<ReturnType<typeof runtime.checkReadiness>>);
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("M-1: stale poll reads re-arm polling but still stop at the 5-read budget", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...finalizing }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;

    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...finalizing, revision: 5 }));
    for (let tick = 0; tick < 10; tick += 1) await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 5);
    expect(screen.getByRole("alert")).toHaveTextContent("Still waiting for the authoritative result after 5 reads");
  });

  it("I-3: a failed event POST keeps the approval a poll already read instead of re-enabling confirm", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
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
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => waiting);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    await flushMicrotasks(1500);
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();

    pendingEvent.reject(new runtime.RuntimeClientError("offline", "network"));
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Keep both unchanged/ })).not.toBeInTheDocument();
    expect(document.getElementById("task-brief-confirm")).toBeDisabled();
    expect(runtime.appendConsumerEvent).toHaveBeenCalledTimes(1);
  });

  it("M-1: a stale (lower-revision) poll read is dropped silently and polling continues", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    const stale = { ...finalizing, revision: 5 };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...finalizing }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;

    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...stale }));
    await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Finalizing the fictional transition" })).toBeInTheDocument();

    await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("E-8: the working Progress artifact shows only steps backed by the accepted payload", async () => {
    const runtime = await import("../../lib/runtime-client");
    const pendingEvent = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(pendingEvent.promise);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(screen.queryByRole("heading", { name: "Comparing fictional Provider options" })).not.toBeInTheDocument();
    const progress = screen.getByRole("heading", { name: "Waiting for the Runtime decision" }).closest("section") as HTMLElement;
    expect(within(progress).queryByText("Guardrails checked")).not.toBeInTheDocument();
    expect(within(progress).getByText("Case revision 2 read")).toBeInTheDocument();
    expect(progress.querySelectorAll("li.done")).toHaveLength(1);
    expect(progress.querySelector("li.active")).toHaveTextContent("Runtime decision");
  });

  it("E-8: the finalizing Progress artifact names the pending execution the Runtime reported", async () => {
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
    await completeLocalIntake(true, [payload(), finalizing]);
    vi.mocked(runtime.getCase).mockResolvedValue(finalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    // M-4: no approved approval in this payload, so the title does not claim one.
    const heading = await screen.findByRole("heading", { name: "Finalizing the fictional transition" });
    expect(screen.queryByRole("heading", { name: "Finalizing the approved fictional transition" })).not.toBeInTheDocument();
    const progress = heading.closest("section") as HTMLElement;
    expect(within(progress).queryByText("Guardrails checked")).not.toBeInTheDocument();
    expect(within(progress).getByText("Case revision 6 read")).toBeInTheDocument();
    expect(progress.querySelectorAll("li.done")).toHaveLength(1);
    expect(progress.querySelector("li.active")).toHaveTextContent("Execution pending");
  });

  it("M-4: the finalizing title says approved only when the payload carries the approved approval", async () => {
    const runtime = await import("../../lib/runtime-client");
    const approvedFinalizing = payload({
      approval: {
        action_intent_revision: 1,
        approval_id: "22222222-2222-4222-8222-222222222222",
        case_revision: 2,
        decision: "approved",
        expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
        material_terms_hash: "hash-1",
      },
      event_cursor: 2,
      revision: 6,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(approvedFinalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.mocked(runtime.getCase).mockResolvedValue(approvedFinalizing);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));

    expect(await screen.findByRole("heading", { name: "Finalizing the approved fictional transition" })).toBeInTheDocument();
  });

  it("E-9: the Usage row renders the projected usage.data_megabytes", async () => {
    const runtime = await import("../../lib/runtime-client");
    const withUsage = {
      ...caseRecord,
      bill_snapshot: { ...caseRecord.bill_snapshot, usage: { data_megabytes: 24576 } },
    };
    const created = payload({ case: withUsage, snapshot: { ...payload().snapshot, case: withUsage } });
    vi.mocked(runtime.createCase).mockResolvedValue(created);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [created]);

    const rail = screen.getByRole("complementary", { name: "Current task context" });
    expect(within(rail).getByText("Usage").nextElementSibling).toHaveTextContent("24,576 MB data");
    expect(within(rail).queryByText("Runtime fact")).not.toBeInTheDocument();
  });

  it("E-9: the Usage row says Unavailable when the projection carries no usage", async () => {
    const runtime = await import("../../lib/runtime-client");
    vi.mocked(runtime.createCase).mockResolvedValue(payload());

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);

    const rail = screen.getByRole("complementary", { name: "Current task context" });
    expect(within(rail).getByText("Usage").nextElementSibling).toHaveTextContent("Unavailable");
    expect(within(rail).queryByText("Runtime fact")).not.toBeInTheDocument();
  });

  it("8b: renders the assistant line from the GET payload after confirmConstraint, never from fast", async () => {
    const runtime = await import("../../lib/runtime-client");
    const approval = {
      action_intent_revision: 1,
      approval_id: "22222222-2222-4222-8222-222222222222",
      case_revision: 2,
      decision: "pending",
      expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
      material_terms_hash: "hash-1",
    };
    // The POST response carries no line and a `fast` echo; only the GET does.
    const posted = payload({
      approval,
      event_cursor: 2,
      fast: { dialogue_act: "clarify", response_text: "FAST ECHO MUST NOT RENDER" },
      revision: 4,
      route: "wait_for_approval",
      snapshot: { ...payload().snapshot, visible_events: [CONSUMER_CONFIRMATION] },
    });
    const read = payload({
      approval,
      event_cursor: 3,
      fast: { dialogue_act: "clarify", response_text: "FAST ECHO MUST NOT RENDER" },
      revision: 4,
      route: "wait_for_approval",
      snapshot: {
        ...payload().snapshot,
        visible_events: [CONSUMER_CONFIRMATION, assistantEvent(3, SCRIPTED_LINE)],
      },
    });
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockResolvedValue(posted);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload(), read]);
    expect(screen.queryByText(AUTOMATED_LABEL)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument());

    const dialogue = screen.getByRole("region", { name: "Automated messages" });
    expect(within(dialogue).getByText(SCRIPTED_LINE)).toBeInTheDocument();
    expect(within(dialogue).getByText(AUTOMATED_LABEL)).toBeInTheDocument();
    expect(screen.queryByText("FAST ECHO MUST NOT RENDER")).not.toBeInTheDocument();
    expect(screen.queryByText("Keep mobile hotspot and device financing unchanged. Continue with the fictional offer.")).not.toBeInTheDocument();
    expect(runtime.getCase).toHaveBeenCalledTimes(2);
    expect(screen.getByPlaceholderText("Message ProxyLoop")).toBeEnabled();
  });

  it("8b: re-renders assistant lines from the authoritative GET on restore", async () => {
    const runtime = await import("../../lib/runtime-client");
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      event_cursor: 5,
      revision: 4,
      snapshot: {
        ...payload().snapshot,
        visible_events: [
          assistantEvent(5, "Second line."),
          CONSUMER_CONFIRMATION,
          assistantEvent(3, SCRIPTED_LINE),
        ],
      },
    }));

    render(<ConversationWorkspace />);

    const dialogue = await screen.findByRole("region", { name: "Automated messages" });
    const lines = within(dialogue).getAllByRole("article");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toHaveTextContent(SCRIPTED_LINE);
    expect(lines[1]).toHaveTextContent("Second line.");
    expect(within(dialogue).getAllByText(AUTOMATED_LABEL)).toHaveLength(2);
    expect(runtime.getCase).toHaveBeenCalledWith(payload().case_id);
  });

  it("8b: renders assistant line content as literal text, never as HTML", async () => {
    const runtime = await import("../../lib/runtime-client");
    const markup = '<script>window.__proxyloopInjected = true</script><img src=x onerror="alert(1)"><b>bold</b>';
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      event_cursor: 3,
      snapshot: { ...payload().snapshot, visible_events: [CONSUMER_CONFIRMATION, assistantEvent(3, markup)] },
    }));

    render(<ConversationWorkspace />);

    const dialogue = await screen.findByRole("region", { name: "Automated messages" });
    expect(within(dialogue).getByText(markup)).toBeInTheDocument();
    expect(dialogue.querySelector("script, img, b")).toBeNull();
    expect((window as unknown as { __proxyloopInjected?: boolean }).__proxyloopInjected).toBeUndefined();
  });

  it.each([
    ["no visible_events", undefined],
    ["only consumer and provider events", [
      visibleEvent(1, "provider", "provider_offer", "Fictional offer."),
      CONSUMER_CONFIRMATION,
    ]],
    ["only malformed assistant entries", [
      visibleEvent(3, "consumer", "assistant_message", "Wrong actor."),
      visibleEvent(4, "system", "assistant_message", 42),
      visibleEvent(-1, "system", "assistant_message", "Negative cursor."),
      visibleEvent(5, "system", "approval_expired", "Wrong type."),
    ]],
  ])("8b: renders no automated message when the payload has %s", async (_label, visibleEvents) => {
    const runtime = await import("../../lib/runtime-client");
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      snapshot: { ...payload().snapshot, visible_events: visibleEvents },
    }));

    render(<ConversationWorkspace />);

    expect(await screen.findByRole("heading", { name: "Here is what I will work from." })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Automated messages" })).not.toBeInTheDocument();
    expect(screen.queryByText(AUTOMATED_LABEL)).not.toBeInTheDocument();
    expect(screen.queryByText("Wrong actor.")).not.toBeInTheDocument();
  });

  it("8b M1: a repeated cursor renders one line and no React key warning", async () => {
    const runtime = await import("../../lib/runtime-client");
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    runtime.savePersistedWorkspace(storedWorkspace(null));
    vi.mocked(runtime.checkReadiness).mockResolvedValue(DURABLE_READY);
    vi.mocked(runtime.getCase).mockResolvedValue(payload({
      event_cursor: 3,
      snapshot: {
        ...payload().snapshot,
        visible_events: [
          CONSUMER_CONFIRMATION,
          assistantEvent(3, SCRIPTED_LINE),
          assistantEvent(3, "A repeated cursor must not render."),
        ],
      },
    }));

    render(<ConversationWorkspace />);

    const dialogue = await screen.findByRole("region", { name: "Automated messages" });
    expect(within(dialogue).getAllByRole("article")).toHaveLength(1);
    expect(within(dialogue).getByText(SCRIPTED_LINE)).toBeInTheDocument();
    expect(screen.queryByText("A repeated cursor must not render.")).not.toBeInTheDocument();
    const keyWarnings = consoleError.mock.calls.filter((call) => call.some(
      (argument) => typeof argument === "string" && argument.includes("same key"),
    ));
    expect(keyWarnings).toEqual([]);
  });

  it("8b M3a: Restart drops Case A's lines and Case B shows none of them", async () => {
    const runtime = await import("../../lib/runtime-client");
    const caseA = payload({
      event_cursor: 3,
      snapshot: { ...payload().snapshot, visible_events: [CONSUMER_CONFIRMATION, assistantEvent(3, "Case A line.")] },
    });
    const caseBRecord = { ...caseRecord, case_id: "33333333-3333-4333-8333-333333333333" };
    const caseB = payload({
      case: caseBRecord,
      case_id: caseBRecord.case_id,
      snapshot: { case: caseBRecord, offers: [offer] },
    });
    vi.mocked(runtime.createCase).mockReset().mockResolvedValueOnce(caseA).mockResolvedValueOnce(caseB);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [caseA]);
    expect(screen.getByText("Case A line.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /New task/ }));
    expect(screen.queryByText("Case A line.")).not.toBeInTheDocument();

    await completeLocalIntake(true, [caseB]);
    expect(runtime.getCase).toHaveBeenLastCalledWith(caseBRecord.case_id);
    expect(screen.queryByText("Case A line.")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Automated messages" })).not.toBeInTheDocument();
  });

  it("8b M3b: a stale poll read (lower revision or cursor) does not roll the lines back", async () => {
    const runtime = await import("../../lib/runtime-client");
    const finalizing = payload({
      event_cursor: 3,
      revision: 6,
      route: "fast_now",
      snapshot: {
        ...payload().snapshot,
        pending_execution: true,
        visible_events: [CONSUMER_CONFIRMATION, assistantEvent(3, SCRIPTED_LINE)],
      },
    });
    const lowerRevision = payload({
      event_cursor: 3,
      revision: 5,
      route: "fast_now",
      snapshot: { ...payload().snapshot, pending_execution: true, visible_events: [CONSUMER_CONFIRMATION] },
    });
    const lowerCursor = { ...lowerRevision, event_cursor: 2, revision: 6 };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(finalizing);

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [payload()]);
    vi.useFakeTimers();
    vi.mocked(runtime.getCase).mockReset().mockImplementation(async () => ({ ...finalizing }));
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await flushMicrotasks();
    expect(screen.getByText(SCRIPTED_LINE)).toBeInTheDocument();
    const reads = vi.mocked(runtime.getCase).mock.calls.length;

    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...lowerRevision }));
    await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 1);
    expect(screen.getByText(SCRIPTED_LINE)).toBeInTheDocument();

    vi.mocked(runtime.getCase).mockImplementation(async () => ({ ...lowerCursor }));
    await flushMicrotasks(1500);
    expect(runtime.getCase).toHaveBeenCalledTimes(reads + 2);
    expect(screen.getByText(SCRIPTED_LINE)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("PR-10: the Agent status bar renders the authoritative snapshot through approval and completion, never fast", async () => {
    const runtime = await import("../../lib/runtime-client");
    const fastEcho = { dialogue_act: "clarify", response_text: "FAST ECHO MUST NOT RENDER" };
    const created = payload({ snapshot: { ...payload().snapshot, offers: [], phase: "strategy" } });
    const approval = {
      action_intent_revision: 1,
      approval_id: "22222222-2222-4222-8222-222222222222",
      case_revision: 2,
      decision: "pending",
      expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
      material_terms_hash: "hash-1",
    };
    const waiting = payload({
      approval,
      fast: fastEcho,
      revision: 4,
      route: "wait_for_approval",
      snapshot: { ...payload().snapshot, phase: "awaiting_approval" },
    });
    const completed = payload({
      approval: { ...approval, decision: "approved" },
      completion: { decision: "complete", evidence_ids: ["evidence-1"] },
      evidence: [{ evidence_id: "evidence-1" }],
      execution_count: 1,
      revision: 7,
      route: "terminal",
      snapshot: { ...payload().snapshot, pending_execution: false, phase: "complete" },
    });
    const eventPost = deferred<RuntimePayload>();
    vi.mocked(runtime.createCase).mockResolvedValue(created);
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockReturnValue(eventPost.promise);
    vi.mocked(runtime.decideApproval).mockResolvedValue(completed);

    render(<ConversationWorkspace />);
    expect(screen.queryByRole("region", { name: "Agent status" })).not.toBeInTheDocument();
    await completeLocalIntake(true, [created, waiting, completed]);

    // The Case waits for the consumer (confirm phase): no planning claim.
    const rail = screen.getByRole("complementary", { name: "Current task context" });
    let bar = within(rail).getByRole("region", { name: "Agent status" });
    expect(bar).toHaveTextContent("Waiting for you to confirm the Task Brief.");
    expect(bar).not.toHaveTextContent("Planning");
    expect(within(bar).getByText("Goal").nextElementSibling).toHaveTextContent("$75.00 or below per month (current bill $92.00)");
    expect(within(bar).getByText("Current offer").nextElementSibling).toHaveTextContent("No offer yet");

    // Planning only while the confirmation command actually runs (working).
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await waitFor(() => expect(within(rail).getByRole("region", { name: "Agent status" })).toHaveTextContent("Planning from your confirmed goal."));
    eventPost.resolve(waiting);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument());
    bar = within(rail).getByRole("region", { name: "Agent status" });
    expect(bar).toHaveTextContent("Waiting for your approval of the exact terms.");
    expect(within(bar).getByText("Approval").nextElementSibling).toHaveTextContent(`Pending · expires ${NORMAL_PENDING_APPROVAL_EXPIRES_AT}`);
    expect(within(bar).getByText("Current offer").nextElementSibling).toHaveTextContent("fictional_mobile_provider · $72.00/month");

    fireEvent.click(screen.getByRole("button", { name: "Approve exact terms" }));
    expect(await screen.findByRole("heading", { name: "Completed with supporting Evidence" })).toBeInTheDocument();
    bar = within(rail).getByRole("region", { name: "Agent status" });
    expect(bar).toHaveTextContent("Done: the Runtime verified completion against Provider Evidence.");
    expect(within(bar).getByText("Completion").nextElementSibling).toHaveTextContent("Verified complete · 1 matching Evidence ID · receipt shown");
    expect(screen.queryByText(/FAST ECHO MUST NOT RENDER/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /New task/ }));
    expect(screen.queryByRole("region", { name: "Agent status" })).not.toBeInTheDocument();
  });

  it("PR-10 I-1: after a rejected read Blocks the workspace, the bar stops describing the held approval", async () => {
    const runtime = await import("../../lib/runtime-client");
    const approval = {
      action_intent_revision: 1,
      approval_id: "22222222-2222-4222-8222-222222222222",
      case_revision: 2,
      decision: "pending",
      expires_at: NORMAL_PENDING_APPROVAL_EXPIRES_AT,
      material_terms_hash: "hash-1",
    };
    const waiting = payload({ approval, revision: 4, route: "wait_for_approval" });
    const driftedCase = { ...caseRecord, bill_snapshot: { monthly_total: { amount_minor: 9300, currency: "USD" } } };
    vi.mocked(runtime.createCase).mockResolvedValue(payload());
    vi.mocked(runtime.appendConsumerEvent).mockReset().mockResolvedValue(waiting);
    vi.mocked(runtime.decideApproval).mockReset().mockResolvedValue(payload({ revision: 5 }));

    render(<ConversationWorkspace />);
    await completeLocalIntake(true, [
      payload(),
      waiting,
      { ...waiting, case: driftedCase, revision: 5, snapshot: { case: driftedCase, offers: [offer] } },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /Keep both unchanged/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Accept these exact fictional terms?" })).toBeInTheDocument());
    const rail = screen.getByRole("complementary", { name: "Current task context" });
    expect(within(rail).getByRole("region", { name: "Agent status" })).toHaveTextContent("Waiting for your approval of the exact terms.");

    fireEvent.click(screen.getByRole("button", { name: "Approve exact terms" }));
    expect(await screen.findByText("Runtime state not verified")).toBeInTheDocument();
    const bar = within(rail).getByRole("region", { name: "Agent status" });
    expect(bar).toHaveTextContent("Stopped — state not verified. Reconnect or restart the local demo.");
    expect(bar).toHaveTextContent("as of Case revision 4");
    expect(bar).not.toHaveTextContent("Waiting for your approval");
  });

  it.each([
    ["$92.00.", "$92.00"],
    ["$92.", "$92.00"],
    ["$12345", "$12,345.00"],
    ["$1,500", "$1,500.00"],
    ["92 USD.", "$92.00"],
    ["$92, thanks", "$92.00"],
    ["$1,500, please", "$1,500.00"],
    ["92 USD, thanks", "$92.00"],
  ])("E-10: accepts the USD input %s as %s", async (input, shown) => {
    render(<ConversationWorkspace />);
    await openEmptyCard();
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: input } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText("Current monthly total").nextElementSibling).toHaveTextContent(shown);
    expect(screen.getAllByText("Missing")).toHaveLength(3);
  });

  it.each([
    "$1,50",
    "$1,500,00",
    "12.345 USD",
    "$92.00.5",
    "$.50",
    "$1,50 or $70",
    "$92, $93",
    "$12,34 then $5",
    "92,5 USD and $4",
    "$92.5 and $1,5",
    "A$92",
    "C$92",
    "HK$92",
    "NZ$92",
    "R$92",
    "US$92",
    "$92 AUD",
    "$92 MXN",
    "$92–95",
    "$92-95",
    "$5-",
  ])("E-10: rejects the ambiguous USD input %s locally", async (input) => {
    render(<ConversationWorkspace />);
    await openEmptyCard();
    fireEvent.change(screen.getByPlaceholderText("Message ProxyLoop"), { target: { value: input } });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Use one non-negative USD value such as $92.00.");
    expect(screen.getAllByText("Missing")).toHaveLength(4);
  });
});

const INCOMPLETE_APPROVAL: RuntimePayload = {
  approval: {
    action_intent_revision: 1,
    approval_id: "22222222-2222-4222-8222-222222222222",
    case_revision: 2,
    decision: "pending",
  },
  case: caseRecord,
  case_id: "11111111-1111-4111-8111-111111111111",
  completion: { decision: "not_done", evidence_ids: [] },
  event_cursor: 2,
  evidence: [],
  execution_count: 0,
  revision: 4,
  route: "wait_for_approval",
  snapshot: { case: caseRecord, offers: [offer] },
};

const DURABLE_READY = {
  status: "ok",
  ready: true,
  dependency: "postgres",
  adapter_mode: "scripted",
  storage_mode: "postgres",
  orchestration_mode: "temporal",
  error_category: "none",
};

const storedPendingEvent = {
  kind: "append_event" as const,
  idempotencyKey: "22222222-2222-4222-8222-222222222222",
  requestBody: {
    content: "Keep mobile hotspot and device financing unchanged.",
    event_type: "consumer_message",
    expected_revision: 2,
  },
  caseId: "11111111-1111-4111-8111-111111111111",
  expectedRevision: 2,
  approvalId: null,
  expectedCaseRevision: null,
  expectedActionIntentRevision: null,
};

function storedWorkspace(pendingCommand: typeof storedPendingEvent | null) {
  return {
    schemaVersion: 1 as const,
    caseId: "11111111-1111-4111-8111-111111111111",
    confirmedFacts: {
      currentMonthlyTotal: { amount_minor: 9200, currency: "USD" as const },
      targetMonthlyTotal: { amount_minor: 7500, currency: "USD" as const },
      mobileHotspotRequired: true as const,
      deviceFinancingChangeForbidden: true as const,
    },
    pendingCommand,
  };
}

const AUTOMATED_LABEL =
  "ProxyLoop AI · automated message — it cannot accept, sign, or change anything without your approval.";
const SCRIPTED_LINE = "Noted. I'll keep your required features and forbidden changes in view.";

// Browser projection of a visible event: exactly VISIBLE_EVENT_KEYS in
// tests/integration/test_browser_projection_allowlist.py (the projection
// drops the canonical event_id).
function visibleEvent(eventCursor: unknown, actor: unknown, eventType: unknown, content: unknown) {
  return {
    actor,
    content,
    event_cursor: eventCursor,
    event_type: eventType,
    occurred_at: "2026-08-25T12:00:00Z",
  };
}

// PR-8 §4.1: a runtime-authored line at trigger cursor + 1, actor SYSTEM.
function assistantEvent(eventCursor: number, content: string) {
  return visibleEvent(eventCursor, "system", "assistant_message", content);
}

const CONSUMER_CONFIRMATION = visibleEvent(
  2,
  "consumer",
  "consumer_message",
  "Keep mobile hotspot and device financing unchanged. Continue with the fictional offer.",
);

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}
