export type JsonObject = Record<string, unknown>;

export type RuntimeApproval = JsonObject & {
  approval_id: string;
  case_revision: number;
  action_intent_revision: number;
  decision: string;
};

export type RuntimeCompletion = JsonObject & {
  decision: string;
  evidence_ids: unknown;
};

export type RuntimeEvidence = JsonObject & {
  evidence_id: string;
};

export type RuntimePayload = {
  case_id: string;
  case: JsonObject;
  snapshot: JsonObject;
  revision: number;
  event_cursor: number;
  route: string;
  approval: RuntimeApproval | null;
  evidence: RuntimeEvidence[];
  completion: RuntimeCompletion;
  execution_count: number;
  [key: string]: unknown;
};

type RuntimeErrorKind = "http" | "invalid" | "network";

export class RuntimeClientError extends Error {
  readonly kind: RuntimeErrorKind;
  readonly status: number | null;

  constructor(
    message: string,
    kind: RuntimeErrorKind,
    status: number | null = null,
  ) {
    super(message);
    this.name = "RuntimeClientError";
    this.kind = kind;
    this.status = status;
  }
}

const RUNTIME_PREFIX = "/api/runtime";

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function objectValue(value: unknown, key: string): JsonObject | null {
  if (!isObject(value)) return null;
  const child = value[key];
  return isObject(child) ? child : null;
}

function arrayValue(value: unknown, key: string): unknown[] {
  if (!isObject(value)) return [];
  const child = value[key];
  return Array.isArray(child) ? child : [];
}

function isNonEmptyStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every((item) => isNonEmptyString(item))
  );
}

export function isValidMoney(value: unknown): value is JsonObject {
  if (!isObject(value)) return false;
  const amountMinor = value.amount_minor;
  return (
    typeof amountMinor === "number" &&
    Number.isFinite(amountMinor) &&
    Number.isInteger(amountMinor) &&
    amountMinor >= 0 &&
    isNonEmptyString(value.currency)
  );
}

export function hasValidTaskBrief(payload: RuntimePayload): boolean {
  const currentCase = objectValue(payload.snapshot, "case");
  const goal = objectValue(currentCase, "goal");
  const bill = objectValue(currentCase, "bill_snapshot");
  return (
    isNonEmptyString(payload.case_id) &&
    isPositiveInteger(payload.revision) &&
    goal !== null &&
    bill !== null &&
    isValidMoney(goal.target_monthly_total) &&
    isValidMoney(bill.monthly_total) &&
    isNonEmptyStringArray(goal.required_features) &&
    isNonEmptyStringArray(goal.forbidden_changes)
  );
}

export function hasValidPendingApproval(payload: RuntimePayload): boolean {
  const approval = payload.approval;
  const offer = arrayValue(payload.snapshot, "offers")[0];
  return (
    approval !== null &&
    approval.decision === "pending" &&
    isNonEmptyString(approval.approval_id) &&
    isNonEmptyString(approval.material_terms_hash) &&
    isNonEmptyString(approval.expires_at) &&
    isPositiveInteger(approval.case_revision) &&
    isPositiveInteger(approval.action_intent_revision) &&
    isObject(offer) &&
    isNonEmptyString(offer.provider_id) &&
    isValidMoney(offer.monthly_price) &&
    isNonNegativeInteger(offer.term_months) &&
    isNonEmptyStringArray(offer.features)
  );
}

function invalidPayload(): RuntimeClientError {
  return new RuntimeClientError(
    "The local Runtime returned an invalid snapshot. Refresh or restart the demo.",
    "invalid",
  );
}

function parsePayload(value: unknown): RuntimePayload {
  if (!isObject(value)) throw invalidPayload();

  const approval = value.approval;
  const evidence = value.evidence;
  const completion = value.completion;
  if (
    !isNonEmptyString(value.case_id) ||
    !isObject(value.case) ||
    !isObject(value.snapshot) ||
    !isPositiveInteger(value.revision) ||
    !isNonNegativeInteger(value.event_cursor) ||
    typeof value.route !== "string" ||
    !Array.isArray(evidence) ||
    !evidence.every(
      (item) => isObject(item) && isNonEmptyString(item.evidence_id),
    ) ||
    !isObject(completion) ||
    typeof completion.decision !== "string" ||
    !isNonNegativeInteger(value.execution_count)
  ) {
    throw invalidPayload();
  }

  if (
    approval !== null &&
    (!isObject(approval) ||
      typeof approval.approval_id !== "string" ||
      !isPositiveInteger(approval.case_revision) ||
      !isPositiveInteger(approval.action_intent_revision) ||
      typeof approval.decision !== "string")
  ) {
    throw invalidPayload();
  }

  return {
    ...value,
    approval: approval as RuntimeApproval | null,
    case: value.case,
    case_id: value.case_id,
    completion: completion as RuntimeCompletion,
    event_cursor: value.event_cursor,
    evidence: evidence as RuntimeEvidence[],
    execution_count: value.execution_count,
    revision: value.revision,
    route: value.route,
    snapshot: value.snapshot,
  };
}

function statusMessage(status: number): string {
  if (status === 409) {
    return "The local Case changed or is waiting for approval. Refresh or restart the demo.";
  }
  if (status === 503) {
    return "The local Runtime is unavailable. Start it and retry, or restart the demo.";
  }
  return "The local Runtime request failed. Retry or restart the demo.";
}

async function request(path: string, init?: RequestInit): Promise<RuntimePayload> {
  let response: Response;
  try {
    response = await fetch(`${RUNTIME_PREFIX}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new RuntimeClientError(
      "The local Runtime could not be reached. Start it and retry, or restart the demo.",
      "network",
    );
  }

  if (!response.ok) {
    throw new RuntimeClientError(statusMessage(response.status), "http", response.status);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw invalidPayload();
  }
  return parsePayload(body);
}

export function createCase(): Promise<RuntimePayload> {
  return request("/cases", { method: "POST" });
}

export function appendConsumerEvent(
  caseId: string,
  content: string,
  expectedRevision?: number,
): Promise<RuntimePayload> {
  return request(`/cases/${encodeURIComponent(caseId)}/events`, {
    body: JSON.stringify({
      content,
      event_type: "consumer_message",
      ...(expectedRevision === undefined
        ? {}
        : { expected_revision: expectedRevision }),
    }),
    method: "POST",
  });
}

export function decideApproval(
  caseId: string,
  approvalId: string,
  pins: {
    expectedRevision: number;
    expectedCaseRevision: number;
    expectedActionIntentRevision: number;
  },
): Promise<RuntimePayload> {
  return request(
    `/cases/${encodeURIComponent(caseId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      body: JSON.stringify({
        decision: "approved",
        expected_action_intent_revision: pins.expectedActionIntentRevision,
        expected_case_revision: pins.expectedCaseRevision,
        expected_revision: pins.expectedRevision,
      }),
      method: "POST",
    },
  );
}

export function completionHasVerifiedEvidence(payload: RuntimePayload): boolean {
  const evidenceIds = payload.completion.evidence_ids;
  return (
    payload.completion.decision === "complete" &&
    payload.execution_count === 1 &&
    Array.isArray(evidenceIds) &&
    evidenceIds.length > 0 &&
    evidenceIds.every(
      (id) =>
      typeof id === "string" &&
        isNonEmptyString(id) &&
        payload.evidence.some(
          (evidence) =>
            isNonEmptyString(evidence.evidence_id) && evidence.evidence_id === id,
        ),
    )
  );
}
