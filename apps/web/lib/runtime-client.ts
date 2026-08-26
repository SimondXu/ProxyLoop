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

export type RuntimeMoney = {
  amount_minor: number;
  currency: "USD";
};

export type IntakeFacts = {
  currentMonthlyTotal: RuntimeMoney;
  targetMonthlyTotal: RuntimeMoney;
  mobileHotspotRequired: true;
  deviceFinancingChangeForbidden: true;
};

export type RuntimeReadiness = {
  status: string;
  ready: boolean;
  dependency: string;
  adapter_mode?: string;
  storage_mode?: string;
  orchestration_mode?: string;
  error_category: string;
};

export type RuntimeErrorCategory =
  | "case_conflict"
  | "case_not_found"
  | "approval_expired"
  | "dependency_not_ready"
  | "storage_unavailable"
  | "temporal_unavailable"
  | "state_invalid"
  | "request_invalid"
  | "model_result_rejected"
  | "network"
  | "invalid"
  | "http_error";

type RuntimeErrorKind = "http" | "invalid" | "network";

export type PersistedPendingCommand = {
  kind: "create_case" | "append_event" | "decide_approval";
  idempotencyKey: string;
  requestBody: JsonObject;
  caseId: string | null;
  expectedRevision: number | null;
  approvalId: string | null;
  expectedCaseRevision: number | null;
  expectedActionIntentRevision: number | null;
};

export type PersistedWorkspaceState = {
  schemaVersion: 1;
  caseId: string | null;
  confirmedFacts: IntakeFacts;
  pendingCommand: PersistedPendingCommand | null;
};

export const RUNTIME_STORAGE_KEY = "proxyloop.runtime:v1";
export const RUNTIME_STORAGE_SCHEMA_VERSION = 1 as const;

export class RuntimeClientError extends Error {
  readonly kind: RuntimeErrorKind;
  readonly status: number | null;
  readonly category: RuntimeErrorCategory;

  constructor(
    message: string,
    kind: RuntimeErrorKind,
    status: number | null = null,
    category: RuntimeErrorCategory = kind === "network"
      ? "network"
      : kind === "invalid"
        ? "invalid"
        : "http_error",
  ) {
    super(message);
    this.name = "RuntimeClientError";
    this.kind = kind;
    this.status = status;
    this.category = category;
  }

  get errorCategory(): RuntimeErrorCategory {
    return this.category;
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

function isUsdMoney(value: unknown): value is RuntimeMoney {
  return (
    isValidMoney(value) &&
    value.currency === "USD" &&
    typeof value.amount_minor === "number"
  );
}

function sameMoney(actual: unknown, expected: RuntimeMoney): boolean {
  return (
    isUsdMoney(actual) &&
    actual.amount_minor === expected.amount_minor &&
    actual.currency === expected.currency
  );
}

function exactStrings(value: unknown, expected: readonly string[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function hasMatchingHardConstraint(currentCase: JsonObject): boolean {
  const constraints = arrayValue(currentCase, "constraints");
  return (
    constraints.length === 1 &&
    constraints.some((item) => {
      const constraint = isObject(item) ? item : null;
      return (
        constraint !== null &&
        constraint.classification === "hard" &&
        constraint.statement === "Do not change device financing."
      );
    })
  );
}

function hasMatchingCase(
  payload: RuntimePayload,
  currentCase: JsonObject,
  expected: IntakeFacts,
): boolean {
  const goal = objectValue(currentCase, "goal");
  const bill = objectValue(currentCase, "bill_snapshot");
  return (
    currentCase.case_id === payload.case_id &&
    goal !== null &&
    bill !== null &&
    sameMoney(goal.target_monthly_total, expected.targetMonthlyTotal) &&
    sameMoney(bill.monthly_total, expected.currentMonthlyTotal) &&
    exactStrings(goal.required_features, ["mobile_hotspot"]) &&
    exactStrings(goal.forbidden_changes, ["device_financing_change"]) &&
    hasMatchingHardConstraint(currentCase)
  );
}

export function hasValidTaskBrief(
  payload: RuntimePayload,
  expected?: IntakeFacts,
): boolean {
  const rootCase = payload.case;
  const snapshotCase = objectValue(payload.snapshot, "case");
  const expectedFacts = expected ?? {
    currentMonthlyTotal: objectValue(snapshotCase, "bill_snapshot")
      ?.monthly_total as RuntimeMoney,
    targetMonthlyTotal: objectValue(
      objectValue(snapshotCase, "goal"),
      "target_monthly_total",
    ) as RuntimeMoney,
    mobileHotspotRequired: true,
    deviceFinancingChangeForbidden: true,
  };
  return (
    isNonEmptyString(payload.case_id) &&
    isPositiveInteger(payload.revision) &&
    snapshotCase !== null &&
    hasMatchingCase(payload, rootCase, expectedFacts) &&
    hasMatchingCase(payload, snapshotCase, expectedFacts)
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
    Number.isFinite(Date.parse(approval.expires_at)) &&
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
  const pendingExecution = isObject(value.snapshot)
    ? value.snapshot.pending_execution
    : undefined;
  if (
    !isNonEmptyString(value.case_id) ||
    !isObject(value.case) ||
    !isObject(value.snapshot) ||
    (pendingExecution !== undefined && typeof pendingExecution !== "boolean") ||
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

const UUID4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function isUuid4(value: unknown): value is string {
  return typeof value === "string" && UUID4_PATTERN.test(value);
}

function hasOnlyKeys(value: JsonObject, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === keys[index]);
}

function isPersistedMoney(value: unknown): value is RuntimeMoney {
  return (
    isObject(value) &&
    hasOnlyKeys(value, ["amount_minor", "currency"]) &&
    typeof value.amount_minor === "number" &&
    Number.isSafeInteger(value.amount_minor) &&
    value.amount_minor >= 0 &&
    value.currency === "USD"
  );
}

function isPersistedFacts(value: unknown): value is IntakeFacts {
  return (
    isObject(value) &&
    hasOnlyKeys(value, [
      "currentMonthlyTotal",
      "deviceFinancingChangeForbidden",
      "mobileHotspotRequired",
      "targetMonthlyTotal",
    ]) &&
    isPersistedMoney(value.currentMonthlyTotal) &&
    isPersistedMoney(value.targetMonthlyTotal) &&
    value.mobileHotspotRequired === true &&
    value.deviceFinancingChangeForbidden === true
  );
}

function isNullablePositiveInteger(value: unknown): value is number | null {
  return value === null || isPositiveInteger(value);
}

function isPersistedRequestBody(
  kind: PersistedPendingCommand["kind"],
  value: unknown,
): value is JsonObject {
  if (!isObject(value)) return false;
  if (kind === "create_case") {
    return (
      hasOnlyKeys(value, [
        "current_monthly_total",
        "device_financing_change_forbidden",
        "mobile_hotspot_required",
        "target_monthly_total",
      ]) &&
      isPersistedMoney(value.current_monthly_total) &&
      isPersistedMoney(value.target_monthly_total) &&
      value.mobile_hotspot_required === true &&
      value.device_financing_change_forbidden === true
    );
  }
  if (kind === "append_event") {
    return (
      hasOnlyKeys(value, ["content", "event_type", "expected_revision"]) &&
      isNonEmptyString(value.content) &&
      value.content.length <= 4000 &&
      value.event_type === "consumer_message" &&
      isPositiveInteger(value.expected_revision)
    );
  }
  return (
    hasOnlyKeys(value, [
      "decision",
      "expected_action_intent_revision",
      "expected_case_revision",
      "expected_revision",
    ]) &&
    value.decision === "approved" &&
    isPositiveInteger(value.expected_revision) &&
    isPositiveInteger(value.expected_case_revision) &&
    isPositiveInteger(value.expected_action_intent_revision)
  );
}

function isPersistedPendingCommand(value: unknown): value is PersistedPendingCommand {
  if (!isObject(value)) return false;
  const kind = value.kind;
  if (kind !== "create_case" && kind !== "append_event" && kind !== "decide_approval") {
    return false;
  }
  if (
    !hasOnlyKeys(value, [
      "approvalId",
      "caseId",
      "expectedActionIntentRevision",
      "expectedCaseRevision",
      "expectedRevision",
      "idempotencyKey",
      "kind",
      "requestBody",
    ]) ||
    !isUuid4(value.idempotencyKey) ||
    value.caseId !== null && !isUuid4(value.caseId) ||
    !isNullablePositiveInteger(value.expectedRevision) ||
    !isNullablePositiveInteger(value.expectedCaseRevision) ||
    !isNullablePositiveInteger(value.expectedActionIntentRevision) ||
    value.approvalId !== null && !isUuid4(value.approvalId) ||
    !isPersistedRequestBody(kind, value.requestBody)
  ) {
    return false;
  }
  if (kind === "create_case") {
    return (
      value.approvalId === null &&
      value.expectedRevision === null &&
      value.expectedCaseRevision === null &&
      value.expectedActionIntentRevision === null
    );
  }
  if (kind === "append_event") {
    return (
      value.caseId !== null &&
      value.approvalId === null &&
      value.expectedRevision !== null &&
      value.expectedCaseRevision === null &&
      value.expectedActionIntentRevision === null
    );
  }
  return (
    value.caseId !== null &&
    value.approvalId !== null &&
    value.expectedRevision !== null &&
    value.expectedCaseRevision !== null &&
    value.expectedActionIntentRevision !== null
  );
}

function isConsistentPendingCommand(
  command: PersistedPendingCommand,
  facts: IntakeFacts,
  caseId: string | null,
): boolean {
  if (command.caseId !== caseId) return false;
  if (command.kind === "create_case") {
    return (
      sameMoney(command.requestBody.current_monthly_total, facts.currentMonthlyTotal) &&
      sameMoney(command.requestBody.target_monthly_total, facts.targetMonthlyTotal) &&
      command.requestBody.mobile_hotspot_required === facts.mobileHotspotRequired &&
      command.requestBody.device_financing_change_forbidden === facts.deviceFinancingChangeForbidden
    );
  }
  if (command.kind === "append_event") {
    return command.requestBody.expected_revision === command.expectedRevision;
  }
  return (
    command.requestBody.expected_revision === command.expectedRevision &&
    command.requestBody.expected_case_revision === command.expectedCaseRevision &&
    command.requestBody.expected_action_intent_revision === command.expectedActionIntentRevision
  );
}

export function isValidPersistedWorkspace(value: unknown): value is PersistedWorkspaceState {
  if (!isObject(value)) return false;
  if (!(
    hasOnlyKeys(value, ["caseId", "confirmedFacts", "pendingCommand", "schemaVersion"]) &&
    value.schemaVersion === RUNTIME_STORAGE_SCHEMA_VERSION &&
    (value.caseId === null || isUuid4(value.caseId)) &&
    isPersistedFacts(value.confirmedFacts) &&
    (value.pendingCommand === null || isPersistedPendingCommand(value.pendingCommand))
  )) return false;
  return value.pendingCommand === null || isConsistentPendingCommand(
    value.pendingCommand,
    value.confirmedFacts,
    value.caseId,
  );
}

export function loadPersistedWorkspace(): PersistedWorkspaceState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(RUNTIME_STORAGE_KEY);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return isValidPersistedWorkspace(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function savePersistedWorkspace(state: PersistedWorkspaceState): void {
  if (!isValidPersistedWorkspace(state) || typeof window === "undefined") return;
  try {
    window.localStorage.setItem(RUNTIME_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Private browsing, disabled storage, and quota errors are non-fatal.
  }
}

export function clearPersistedWorkspace(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(RUNTIME_STORAGE_KEY);
  } catch {
    // Storage is only a best-effort locator and retry aid.
  }
}

const ERROR_CATEGORIES = new Set<RuntimeErrorCategory>([
  "approval_expired",
  "case_conflict",
  "case_not_found",
  "dependency_not_ready",
  "model_result_rejected",
  "request_invalid",
  "state_invalid",
  "storage_unavailable",
  "temporal_unavailable",
]);

function errorCategory(status: number, body: unknown): RuntimeErrorCategory {
  const detail = objectValue(body, "detail");
  const code = detail && typeof detail.code === "string" ? detail.code : null;
  if (code && ERROR_CATEGORIES.has(code as RuntimeErrorCategory)) {
    return code as RuntimeErrorCategory;
  }
  if (status === 404) return "case_not_found";
  if (status === 409) return "case_conflict";
  if (status === 422) return "request_invalid";
  if (status === 503) return "temporal_unavailable";
  return "http_error";
}

function statusMessage(category: RuntimeErrorCategory): string {
  if (category === "case_not_found") {
    return "The saved Case is no longer available in the local Runtime. Reset this local task to continue.";
  }
  if (category === "case_conflict") {
    return "The local Case changed concurrently. I will read its current authoritative state before continuing.";
  }
  if (category === "approval_expired") {
    return "The Runtime reports that this approval has expired. No approval was sent again.";
  }
  if (category === "dependency_not_ready" || category === "storage_unavailable") {
    return "The local Runtime dependencies are not ready. Your Case and safe retry remain preserved.";
  }
  if (category === "temporal_unavailable") {
    return "The local orchestration attempt is still unresolved. Your Case and safe retry remain preserved; reconnect to read authoritative state.";
  }
  if (category === "state_invalid" || category === "request_invalid" || category === "model_result_rejected") {
    return "The local Runtime rejected this state safely. No unverified result is shown.";
  }
  return "The local Runtime request failed safely. Reconnect and retry when ready.";
}

function idempotencyKey(options?: { idempotencyKey?: string }): string {
  const key = options?.idempotencyKey ?? crypto.randomUUID();
  if (!isUuid4(key)) {
    throw new RuntimeClientError(
      "The command identity is invalid. No Runtime request was sent.",
      "invalid",
      null,
      "invalid",
    );
  }
  return key;
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
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
      null,
      "network",
    );
  }

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    if (response.ok) throw invalidPayload();
  }
  if (!response.ok) {
    const category = errorCategory(response.status, body);
    throw new RuntimeClientError(
      statusMessage(category),
      "http",
      response.status,
      category,
    );
  }
  return body;
}

async function request(path: string, init?: RequestInit): Promise<RuntimePayload> {
  return parsePayload(await requestJson(path, init));
}

export function createCase(
  facts: IntakeFacts,
  options?: { idempotencyKey?: string },
): Promise<RuntimePayload> {
  const body = createCaseRequestBody(facts);
  const key = idempotencyKey(options);
  return request("/cases", {
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": key },
    method: "POST",
  });
}

export function appendConsumerEvent(
  caseId: string,
  content: string,
  expectedRevisionOrOptions?: number | { expectedRevision?: number; idempotencyKey?: string },
  options?: { idempotencyKey?: string },
): Promise<RuntimePayload> {
  const expectedRevision = typeof expectedRevisionOrOptions === "number"
    ? expectedRevisionOrOptions
    : expectedRevisionOrOptions?.expectedRevision;
  const body = appendConsumerEventRequestBody(content, expectedRevision);
  const key = idempotencyKey(
    typeof expectedRevisionOrOptions === "object"
      ? expectedRevisionOrOptions
      : options,
  );
  return request(`/cases/${encodeURIComponent(caseId)}/events`, {
    body: JSON.stringify(body),
    headers: { "Idempotency-Key": key },
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
  options?: { idempotencyKey?: string },
): Promise<RuntimePayload> {
  const body = decideApprovalRequestBody(pins);
  const key = idempotencyKey(options);
  return request(
    `/cases/${encodeURIComponent(caseId)}/approvals/${encodeURIComponent(approvalId)}`,
    {
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": key },
      method: "POST",
    },
  );
}

export function getCase(caseId: string): Promise<RuntimePayload> {
  return request(`/cases/${encodeURIComponent(caseId)}`, { method: "GET" });
}

function parseReadiness(value: unknown): RuntimeReadiness {
  if (!isObject(value) || typeof value.status !== "string" ||
      typeof value.ready !== "boolean" || !isNonEmptyString(value.dependency)) {
    throw invalidPayload();
  }
  const detail = objectValue(value, "detail");
  const detailCode = detail && typeof detail.code === "string" ? detail.code : "none";
  if (detailCode !== "none" && !ERROR_CATEGORIES.has(detailCode as RuntimeErrorCategory)) {
    throw invalidPayload();
  }
  const modes = ["adapter_mode", "storage_mode", "orchestration_mode"] as const;
  if (modes.some((key) => value[key] !== undefined && typeof value[key] !== "string")) {
    throw invalidPayload();
  }
  return {
    status: value.status,
    ready: value.ready,
    dependency: value.dependency,
    adapter_mode: value.adapter_mode as string | undefined,
    storage_mode: value.storage_mode as string | undefined,
    orchestration_mode: value.orchestration_mode as string | undefined,
    error_category: detailCode,
  };
}

export async function checkReadiness(): Promise<RuntimeReadiness> {
  try {
    return parseReadiness(await requestJson("/health/ready"));
  } catch (caught) {
    if (caught instanceof RuntimeClientError && caught.status === 503) {
      return {
        status: "unavailable",
        ready: false,
        dependency: "runtime",
        error_category: caught.category,
      };
    }
    throw caught;
  }
}

export const getReadiness = checkReadiness;

export function createCaseRequestBody(facts: IntakeFacts): JsonObject {
  return {
    current_monthly_total: facts.currentMonthlyTotal,
    target_monthly_total: facts.targetMonthlyTotal,
    mobile_hotspot_required: facts.mobileHotspotRequired,
    device_financing_change_forbidden: facts.deviceFinancingChangeForbidden,
  };
}

export function appendConsumerEventRequestBody(
  content: string,
  expectedRevision?: number,
): JsonObject {
  return {
    content,
    event_type: "consumer_message",
    ...(expectedRevision === undefined ? {} : { expected_revision: expectedRevision }),
  };
}

export function decideApprovalRequestBody(
  pins: {
    expectedRevision: number;
    expectedCaseRevision: number;
    expectedActionIntentRevision: number;
  },
): JsonObject {
  return {
    decision: "approved",
    expected_action_intent_revision: pins.expectedActionIntentRevision,
    expected_case_revision: pins.expectedCaseRevision,
    expected_revision: pins.expectedRevision,
  };
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
