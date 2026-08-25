"use client";

import type { FormEvent, ReactNode } from "react";
import { useRef, useState } from "react";

import {
  appendConsumerEvent,
  completionHasVerifiedEvidence,
  createCase,
  decideApproval,
  hasValidPendingApproval,
  hasValidTaskBrief,
  type IntakeFacts,
  type JsonObject,
  RuntimeClientError,
  type RuntimeMoney,
  type RuntimePayload,
} from "../../lib/runtime-client";
import { StatusBadge } from "./status-badge";

type WorkspacePhase =
  | "loading"
  | "blank"
  | "intake"
  | "confirm"
  | "working"
  | "approval"
  | "receipt"
  | "blocked";

type Message = { id: number; role: "assistant" | "user"; text: string };
type IntakeField = "current" | "target" | "hotspot" | "financing";
type IntakeDraft = {
  currentMonthlyTotal: RuntimeMoney | null;
  targetMonthlyTotal: RuntimeMoney | null;
  mobileHotspotRequired: true | null;
  deviceFinancingChangeForbidden: true | null;
};

const EMPTY_INTAKE: IntakeDraft = {
  currentMonthlyTotal: null,
  targetMonthlyTotal: null,
  mobileHotspotRequired: null,
  deviceFinancingChangeForbidden: null,
};

const CONFIRMATION_EVENT =
  "Keep mobile hotspot and device financing unchanged. Continue with the fictional offer.";

const MOBILE_TERMS = /\b(?:mobile|cell(?:ular)?|phone)\b/i;
const BILLING_CONTEXT_TERMS = /\b(?:bill|cost|price|plan|monthly)\b/i;
const REDUCTION_OUTCOME_TERMS = /\b(?:lower|reduce|save|saving|savings|cheaper|decrease|cut)\b/i;

export function isSupportedMobileBillIntent(text: string): boolean {
  return (
    MOBILE_TERMS.test(text) &&
    BILLING_CONTEXT_TERMS.test(text) &&
    REDUCTION_OUTCOME_TERMS.test(text)
  );
}

function firstMissingIntakeField(draft: IntakeDraft): IntakeField | null {
  if (draft.currentMonthlyTotal === null) return "current";
  if (draft.targetMonthlyTotal === null) return "target";
  if (draft.mobileHotspotRequired === null) return "hotspot";
  if (draft.deviceFinancingChangeForbidden === null) return "financing";
  return null;
}

function intakePrompt(field: IntakeField): string {
  if (field === "current") {
    return "What is your current monthly bill total in USD? Use a value such as $92.00.";
  }
  if (field === "target") {
    return "What monthly total would you like to reach in USD? The fictional $72 offer requires a target from $72 up to your current bill.";
  }
  if (field === "hotspot") {
    return "Do you need mobile hotspot access kept? Reply yes or no. This local journey requires it to stay on.";
  }
  return "Should device financing remain unchanged? Reply yes or no. This local journey cannot change financing.";
}

function parseUsdMoney(text: string): RuntimeMoney | null {
  if (/[€£¥]|\b(?:EUR|CAD|GBP|JPY)\b/i.test(text) || /-\s*\$?\s*\d/.test(text)) {
    return null;
  }
  const matches = [...text.matchAll(/(?:\$\s*(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)(?![\dA-Za-z.])|(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)\s*USD\b)/gi)];
  if (matches.length !== 1) return null;
  const raw = matches[0][1] ?? matches[0][2];
  if (!raw) return null;
  const normalised = raw.replaceAll(",", "");
  const [whole, fraction = ""] = normalised.split(".");
  const amountMinor = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(amountMinor) && amountMinor >= 0
    ? { amount_minor: amountMinor, currency: "USD" }
    : null;
}

function parseBooleanFact(text: string, field: "hotspot" | "financing"): true | null {
  const normalized = text
    .trim()
    .toLowerCase()
    .replace(/^[.,!?;:]+|[.,!?;:]+$/g, "")
    .trim()
    .replace(/\s+/g, " ");
  if (field === "financing") {
    const confirmations = new Set([
      "yes",
      "true",
      "unchanged",
      "no change",
      "no changes",
      "keep unchanged",
      "keep it unchanged",
    ]);
    return confirmations.has(normalized) ? true : null;
  }
  const confirmations = new Set(["yes", "true", "required", "keep it"]);
  return confirmations.has(normalized) ? true : null;
}

function intakeFacts(draft: IntakeDraft): IntakeFacts | null {
  if (
    draft.currentMonthlyTotal === null ||
    draft.targetMonthlyTotal === null ||
    draft.mobileHotspotRequired !== true ||
    draft.deviceFinancingChangeForbidden !== true
  ) {
    return null;
  }
  return {
    currentMonthlyTotal: draft.currentMonthlyTotal,
    targetMonthlyTotal: draft.targetMonthlyTotal,
    mobileHotspotRequired: true,
    deviceFinancingChangeForbidden: true,
  };
}

function intakeValueError(field: IntakeField, draft: IntakeDraft): string | null {
  const current = draft.currentMonthlyTotal?.amount_minor;
  const target = draft.targetMonthlyTotal?.amount_minor;
  if (field === "current") {
    if (current !== undefined && current <= 7200) {
      return "The current bill must be greater than $72.00 for this fictional offer.";
    }
    return current !== undefined && target !== undefined && target >= current
      ? "The current bill must stay above the confirmed target. Enter a higher current USD amount."
      : null;
  }
  if (field === "target") {
    if (target !== undefined && target < 7200) {
      return "The target must be at least $72.00.";
    }
    if (target !== undefined && current !== undefined && target >= current) {
      return "The target must stay below the confirmed current bill. Enter a lower USD amount.";
    }
  }
  return null;
}

function objectAt(value: unknown, key: string): JsonObject | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const child = (value as JsonObject)[key];
  return typeof child === "object" && child !== null && !Array.isArray(child)
    ? (child as JsonObject)
    : null;
}

function arrayAt(value: unknown, key: string): unknown[] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return [];
  }
  const child = (value as JsonObject)[key];
  return Array.isArray(child) ? child : [];
}

function stringAt(value: unknown, key: string): string | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const child = (value as JsonObject)[key];
  return typeof child === "string" && child.trim() ? child : null;
}

function integerAt(value: unknown, key: string): number | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const child = (value as JsonObject)[key];
  return typeof child === "number" && Number.isInteger(child) ? child : null;
}

function humanize(value: string): string {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatMoney(value: unknown): string {
  const amountMinor = integerAt(value, "amount_minor");
  const currency = stringAt(value, "currency");
  if (amountMinor === null || currency === null) return "Unavailable";
  try {
    return new Intl.NumberFormat("en-US", {
      currency,
      maximumFractionDigits: 2,
      style: "currency",
    }).format(amountMinor / 100);
  } catch {
    return `${currency} ${(amountMinor / 100).toFixed(2)}`;
  }
}

function caseRecord(payload: RuntimePayload): JsonObject | null {
  return objectAt(payload.snapshot, "case");
}

function goalRecord(payload: RuntimePayload): JsonObject | null {
  const currentCase = caseRecord(payload);
  return currentCase ? objectAt(currentCase, "goal") : null;
}

function billRecord(payload: RuntimePayload): JsonObject | null {
  const currentCase = caseRecord(payload);
  return currentCase ? objectAt(currentCase, "bill_snapshot") : null;
}

function labelsAt(value: unknown[], key: string): string[] {
  return value.flatMap((item) => {
    if (typeof item === "string") return [humanize(item)];
    const label = stringAt(item, key) ?? stringAt(item, "statement");
    return label ? [label] : [];
  });
}

function AssistantMessage({ children }: { children: ReactNode }) {
  return (
    <article className="chat-turn assistant-turn">
      <div aria-hidden="true" className="assistant-avatar">✦</div>
      <div className="message-stack">
        <span className="message-author">ProxyLoop</span>
        <div className="message-bubble">{children}</div>
      </div>
    </article>
  );
}

function UserMessage({ children }: { children: ReactNode }) {
  return (
    <article className="chat-turn user-turn">
      <div className="message-stack">
        <span className="message-author">You</span>
        <div className="message-bubble">{children}</div>
      </div>
    </article>
  );
}

function DraftTaskBrief({
  draft,
  activeField,
  intakeError,
  busy,
  onEdit,
  onCreate,
}: {
  draft: IntakeDraft;
  activeField: IntakeField | null;
  intakeError: string | null;
  busy: boolean;
  onEdit: (field: IntakeField) => void;
  onCreate: () => void;
}) {
  const facts = [
    {
      field: "current" as const,
      label: "Current monthly total",
      value: draft.currentMonthlyTotal === null ? "Missing" : formatMoney(draft.currentMonthlyTotal),
    },
    {
      field: "target" as const,
      label: "Target monthly total",
      value: draft.targetMonthlyTotal === null ? "Missing" : formatMoney(draft.targetMonthlyTotal),
    },
    {
      field: "hotspot" as const,
      label: "Mobile hotspot required",
      value: draft.mobileHotspotRequired === true ? "Confirmed · required" : "Missing",
    },
    {
      field: "financing" as const,
      label: "Device financing change forbidden",
      value: draft.deviceFinancingChangeForbidden === true ? "Confirmed · unchanged" : "Missing",
    },
  ];
  const ready =
    activeField === null &&
    intakeError === null &&
    intakeFacts(draft) !== null &&
    intakeValueError("current", draft) === null &&
    intakeValueError("target", draft) === null;

  return (
    <section aria-labelledby="draft-task-brief-title" className="chat-artifact draft-task-brief">
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Local intake · Draft Task Brief</span>
          <h2 id="draft-task-brief-title">Confirm the facts before creating a Case.</h2>
        </div>
        <StatusBadge tone={ready ? "complete" : "neutral"}>{ready ? "Ready" : "Needs input"}</StatusBadge>
      </div>
      <dl className="artifact-facts draft-facts">
        {facts.map((fact) => (
          <div key={fact.field}>
            <dt>{fact.label}</dt>
            <dd>
              <span>{fact.value}</span>
              <button className="fact-edit" disabled={busy} onClick={() => onEdit(fact.field)} type="button">
                {activeField === fact.field ? "Editing" : "Edit"}
              </button>
            </dd>
          </div>
        ))}
      </dl>
      <p className="artifact-note">
        These facts stay local until you choose the explicit create action. The Runtime will receive exactly these four fields.
      </p>
      <button className="primary-button" disabled={!ready || busy} onClick={onCreate} type="button">
        {busy ? "Creating fictional Case…" : "Create fictional Case"}
        <span aria-hidden="true">→</span>
      </button>
    </section>
  );
}

function TaskBriefArtifact({
  payload,
  onConfirm,
}: {
  payload: RuntimePayload;
  onConfirm?: () => void;
}) {
  const goal = goalRecord(payload);
  const bill = billRecord(payload);
  const required = labelsAt(arrayAt(goal, "required_features"), "");
  const forbidden = labelsAt(arrayAt(goal, "forbidden_changes"), "");

  return (
    <section aria-labelledby="task-brief-title" className="chat-artifact fact-artifact">
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Task brief · Runtime snapshot</span>
          <h2 id="task-brief-title">Here is what I will work from.</h2>
        </div>
        <StatusBadge tone="complete">Verified snapshot</StatusBadge>
      </div>
      <dl className="artifact-facts">
        <div><dt>Current monthly total</dt><dd>{formatMoney(objectAt(bill, "monthly_total"))}</dd></div>
        <div><dt>Target</dt><dd>{formatMoney(objectAt(goal, "target_monthly_total"))} or below</dd></div>
        <div><dt>Keep</dt><dd>{required.join(", ") || "Unavailable"}</dd></div>
        <div><dt>Never change</dt><dd>{forbidden.join(", ") || "Unavailable"}</dd></div>
      </dl>
      <p className="artifact-note">
        I created this Case locally. Confirming the constraint below is the only
        consumer event this demo sends to the Runtime.
      </p>
      <button
        className="primary-button"
        disabled={!onConfirm}
        id="task-brief-confirm"
        onClick={onConfirm}
        type="button"
      >
        {onConfirm ? "Keep both unchanged and continue" : "Constraint confirmed"}
        <span aria-hidden="true">→</span>
      </button>
    </section>
  );
}

function ProgressArtifact({ label = "Comparing fictional Provider options" }: { label?: string }) {
  return (
    <section aria-labelledby="progress-title" className="chat-artifact progress-artifact">
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Runtime progress</span>
          <h2 id="progress-title">{label}</h2>
        </div>
        <StatusBadge tone="working">Working</StatusBadge>
      </div>
      <ol className="activity-list">
        <li className="done"><span aria-hidden="true">✓</span><span><strong>Case snapshot read</strong><small>Bill and constraints are pinned.</small></span></li>
        <li className="done"><span aria-hidden="true">✓</span><span><strong>Guardrails checked</strong><small>Hotspot and device financing remain protected.</small></span></li>
        <li className="active"><span aria-hidden="true">◷</span><span><strong>Runtime decision</strong><small>Waiting for the authoritative response.</small></span></li>
      </ol>
    </section>
  );
}

function OfferArtifact({ payload }: { payload: RuntimePayload }) {
  const offer = arrayAt(payload.snapshot, "offers")[0];
  const provider = stringAt(offer, "provider_id") ?? "Fictional Provider";
  const features = labelsAt(arrayAt(offer, "features"), "");
  const bill = billRecord(payload);
  const currentMinor = integerAt(objectAt(bill, "monthly_total"), "amount_minor");
  const newMinor = integerAt(objectAt(offer, "monthly_price"), "amount_minor");
  const savings = currentMinor !== null && newMinor !== null
    ? formatMoney({ amount_minor: currentMinor - newMinor, currency: stringAt(objectAt(bill, "monthly_total"), "currency") ?? "USD" })
    : "Unavailable";

  return (
    <section aria-labelledby="offer-title" className="chat-artifact offer-artifact">
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Offer found · Runtime response</span>
          <h2 id="offer-title">{provider}</h2>
        </div>
        <span className="provider-label">Nothing accepted</span>
      </div>
      <div className="offer-price-row">
        <div><span>New monthly price</span><strong>{formatMoney(objectAt(offer, "monthly_price"))}</strong></div>
        <div><span>Monthly savings</span><strong>{savings}</strong></div>
        <div><span>Term</span><strong>{integerAt(offer, "term_months") ?? "—"} months</strong></div>
      </div>
      <ul className="artifact-checks">
        {features.map((feature) => <li key={feature}><span aria-hidden="true">✓</span>{feature}</li>)}
      </ul>
      <p className="artifact-note">Review these exact Runtime terms before approval. Approval is still required.</p>
    </section>
  );
}

function ApprovalArtifact({
  payload,
  onApprove,
  busy,
}: {
  payload: RuntimePayload;
  onApprove: () => void;
  busy: boolean;
}) {
  const approval = payload.approval;
  if (!approval || !hasValidPendingApproval(payload)) return null;
  const offer = arrayAt(payload.snapshot, "offers")[0];

  return (
    <section aria-labelledby="approval-title" className="chat-artifact approval-artifact">
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Your approval is required</span>
          <h2 id="approval-title">Accept these exact fictional terms?</h2>
        </div>
        <StatusBadge>Approval boundary</StatusBadge>
      </div>
      <dl className="approval-inline-terms">
        <div><dt>Provider</dt><dd>{stringAt(offer, "provider_id") ?? "Unavailable"}</dd></div>
        <div><dt>Monthly price</dt><dd>{formatMoney(objectAt(offer, "monthly_price"))}</dd></div>
        <div><dt>Case revision</dt><dd>{approval.case_revision}</dd></div>
        <div><dt>Expires</dt><dd>{stringAt(approval, "expires_at") ?? "Unavailable"}</dd></div>
      </dl>
      <details className="hash-details">
        <summary>View exact version binding</summary>
        <p>Runtime revision {payload.revision} · Action Intent revision {approval.action_intent_revision}</p>
        <code>{stringAt(approval, "material_terms_hash") ?? "Unavailable"}</code>
      </details>
      <p className="artifact-note">
        The approval request uses the Runtime&apos;s returned Case revision and
        Action Intent revision. The UI does not create or increment either value.
      </p>
      <button className="primary-button" disabled={busy} id="approval-primary-action" onClick={onApprove} type="button">
        {busy ? "Sending exact approval…" : "Approve exact terms"}
        <span aria-hidden="true">→</span>
      </button>
    </section>
  );
}

function ReceiptArtifact({ payload }: { payload: RuntimePayload }) {
  const offer = arrayAt(payload.snapshot, "offers")[0];
  const bill = billRecord(payload);
  const currentMinor = integerAt(objectAt(bill, "monthly_total"), "amount_minor");
  const newMinor = integerAt(objectAt(offer, "monthly_price"), "amount_minor");
  const currency = stringAt(objectAt(bill, "monthly_total"), "currency") ?? "USD";
  const savings = currentMinor !== null && newMinor !== null
    ? formatMoney({ amount_minor: currentMinor - newMinor, currency })
    : "Unavailable";
  const evidenceIds = Array.isArray(payload.completion.evidence_ids)
    ? payload.completion.evidence_ids.filter((id): id is string => typeof id === "string")
    : [];

  return (
    <section aria-labelledby="receipt-title" className="chat-artifact receipt-artifact" id="receipt-artifact" tabIndex={-1}>
      <div className="artifact-heading">
        <div>
          <span className="artifact-kicker">Evidence receipt</span>
          <h2 id="receipt-title">Completed with supporting Evidence</h2>
        </div>
        <StatusBadge tone="complete">Verified</StatusBadge>
      </div>
      <div className="receipt-summary-row">
        <div><span>Previous</span><strong>{formatMoney(objectAt(bill, "monthly_total"))}</strong></div>
        <span aria-hidden="true" className="receipt-arrow">→</span>
        <div><span>New monthly</span><strong>{formatMoney(objectAt(offer, "monthly_price"))}</strong></div>
        <div className="savings-cell"><span>Savings</span><strong>{savings}</strong></div>
      </div>
      <div className="evidence-line">
        <span aria-hidden="true" className="evidence-icon">▣</span>
        <span>Runtime completion Evidence</span>
        <small>{evidenceIds.length} matched Evidence IDs · execution count {payload.execution_count}</small>
      </div>
      <p className="artifact-note">Every displayed Evidence ID matched the returned Evidence list.</p>
    </section>
  );
}

function RuntimeErrorState({ error, onRestart }: { error: string; onRestart: () => void }) {
  return (
    <section aria-live="assertive" className="runtime-error" role="alert">
      <strong>Runtime state not verified</strong>
      <p>{error}</p>
      <button className="secondary-button" onClick={onRestart} type="button">Restart local demo</button>
    </section>
  );
}

export function ConversationWorkspace() {
  const [phase, setPhase] = useState<WorkspacePhase>("blank");
  const [payload, setPayload] = useState<RuntimePayload | null>(null);
  const [confirmedFacts, setConfirmedFacts] = useState<IntakeFacts | null>(null);
  const [intake, setIntake] = useState<IntakeDraft>(EMPTY_INTAKE);
  const [activeField, setActiveField] = useState<IntakeField | null>(null);
  const [intakeError, setIntakeError] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nextMessageId = useRef(1);
  const sessionId = useRef(0);

  function addMessage(role: Message["role"], text: string) {
    const id = nextMessageId.current;
    nextMessageId.current += 1;
    setMessages((current) => [...current, { id, role, text }]);
  }

  async function loadCase(facts: IntakeFacts) {
    const requestId = sessionId.current + 1;
    sessionId.current = requestId;
    setPhase("loading");
    setBusy(true);
    setError(null);
    try {
      const created = await createCase(facts);
      if (requestId !== sessionId.current) return;
      if (!hasValidTaskBrief(created, facts)) {
        throw new RuntimeClientError(
          "The local Runtime returned a Case that does not match your confirmed facts. No verified Task Brief is shown; restart the local demo.",
          "invalid",
        );
      }
      setConfirmedFacts(facts);
      setPayload(created);
      setPhase("confirm");
    } catch (caught) {
      if (requestId !== sessionId.current) return;
      setPhase("blocked");
      setError(caught instanceof Error ? caught.message : "The local Runtime failed safely. Refresh or restart the demo.");
    } finally {
      if (requestId === sessionId.current) setBusy(false);
    }
  }

  function restart() {
    sessionId.current += 1;
    setMessages([]);
    setDraft("");
    setPayload(null);
    setConfirmedFacts(null);
    setIntake(EMPTY_INTAKE);
    setActiveField(null);
    setIntakeError(null);
    setError(null);
    setBusy(false);
    setPhase("blank");
    nextMessageId.current = 1;
  }

  function editIntakeField(field: IntakeField) {
    if (phase !== "intake" || busy) return;
    setActiveField(field);
    setIntakeError(null);
    addMessage("assistant", intakePrompt(field));
  }

  function createIntakeCase() {
    const facts = intakeFacts(intake);
    if (
      !facts ||
      intakeValueError("current", intake) !== null ||
      intakeValueError("target", intake) !== null ||
      busy
    ) return;
    addMessage("assistant", "I am sending the four confirmed intake facts to the local Runtime now.");
    void loadCase(facts);
  }

  function submitIntakeValue(text: string) {
    const field = activeField ?? firstMissingIntakeField(intake);
    if (!field) return;
    let next = intake;
    if (field === "current" || field === "target") {
      const value = parseUsdMoney(text);
      if (value === null) {
        setIntakeError("Use one non-negative USD value such as $92.00. Other currencies, negative values, or ambiguous amounts stay local.");
        addMessage("assistant", "I could not confirm that USD amount. Please enter one value such as $92.00.");
        return;
      }
      next = field === "current"
        ? { ...intake, currentMonthlyTotal: value }
        : { ...intake, targetMonthlyTotal: value };
      const valueError = intakeValueError(field, next);
      if (valueError) {
        setIntakeError(valueError);
        addMessage("assistant", valueError);
        return;
      }
    } else {
      const value = parseBooleanFact(text, field);
      if (value !== true) {
        const label = field === "hotspot" ? "Mobile hotspot must remain required" : "Device financing must remain unchanged";
        setIntakeError(`${label}. Reply yes to confirm this fixed constraint.`);
        addMessage("assistant", `${label}. Reply yes to confirm, or edit another local fact.`);
        return;
      }
      next = field === "hotspot"
        ? { ...intake, mobileHotspotRequired: true }
        : { ...intake, deviceFinancingChangeForbidden: true };
    }
    setIntake(next);
    setIntakeError(null);
    const nextField = firstMissingIntakeField(next);
    setActiveField(nextField);
    addMessage(
      "assistant",
      nextField ? intakePrompt(nextField) : "All four facts are confirmed locally. Review the Draft Task Brief, then choose Create fictional Case when it matches.",
    );
  }

  async function confirmConstraint() {
    if (!payload || busy) return;
    const requestId = sessionId.current;
    setBusy(true);
    setError(null);
    addMessage("user", "Keep mobile hotspot and device financing unchanged.");
    setPhase("working");
    try {
      const waiting = await appendConsumerEvent(payload.case_id, CONFIRMATION_EVENT, payload.revision);
      if (requestId !== sessionId.current) return;
      if (confirmedFacts && hasValidTaskBrief(waiting, confirmedFacts) && hasValidPendingApproval(waiting)) {
        setPayload(waiting);
        setPhase("approval");
      } else {
        setPayload(null);
        setPhase("blocked");
        setError("The Runtime returned missing or mismatched intake facts. No approval is available; restart the local Runtime, then choose New task.");
      }
    } catch (caught) {
      if (requestId !== sessionId.current) return;
      setPhase("confirm");
      setError(caught instanceof Error ? caught.message : "The Runtime failed safely. Retry or restart the demo.");
    } finally {
      if (requestId === sessionId.current) setBusy(false);
    }
  }

  async function approveExactTerms() {
    if (!payload?.approval || busy) return;
    const requestId = sessionId.current;
    const waiting = payload;
    const approval = waiting.approval;
    if (!approval || !confirmedFacts || !hasValidTaskBrief(waiting, confirmedFacts) || !hasValidPendingApproval(waiting)) return;
    setBusy(true);
    setError(null);
    try {
      const completed = await decideApproval(waiting.case_id, approval.approval_id, {
        expectedActionIntentRevision: approval.action_intent_revision,
        expectedCaseRevision: approval.case_revision,
        expectedRevision: waiting.revision,
      });
      if (requestId !== sessionId.current) return;
      if (confirmedFacts && hasValidTaskBrief(completed, confirmedFacts) && completionHasVerifiedEvidence(completed)) {
        setPayload(completed);
        setPhase("receipt");
      } else {
        setPayload(null);
        setPhase("blocked");
        setError("The Runtime response did not preserve the confirmed intake facts or verifiable completion Evidence. No success is shown; restart the local Runtime, then choose New task.");
      }
    } catch (caught) {
      if (requestId !== sessionId.current) return;
      setPhase("approval");
      setError(caught instanceof Error ? caught.message : "The Runtime failed safely. Retry or restart the demo.");
    } finally {
      if (requestId === sessionId.current) setBusy(false);
    }
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy || phase === "loading") return;
    addMessage("user", text);
    setDraft("");
    if (phase === "blank") {
      if (!isSupportedMobileBillIntent(text)) {
        addMessage(
          "assistant",
          "This local demo only supports lowering a fictional mobile bill. Try a clear request such as “Lower my mobile bill.”",
        );
        return;
      }
      setPhase("intake");
      setActiveField("current");
      addMessage("assistant", intakePrompt("current"));
      return;
    }
    if (phase === "intake") {
      submitIntakeValue(text);
      return;
    }
    if (phase === "confirm") {
      addMessage("assistant", "This Case is immutable after creation. To change a confirmed fact, restart the local Runtime, then choose New task.");
      return;
    }
    if (phase === "approval") {
      addMessage("assistant", "This Case is waiting for the exact approval shown above. To correct a confirmed fact, restart the local Runtime, then choose New task; this demo has no mutation endpoint.");
      return;
    }
    if (phase === "receipt") {
      addMessage("assistant", "This Case is complete and read-only. To correct a confirmed fact, restart the local Runtime, then choose New task.");
      return;
    }
    addMessage("assistant", "The local Runtime is blocked, so I did not continue. Restart the demo to obtain a fresh Case.");
  }

  const status = phase === "receipt"
    ? "Verified"
    : phase === "approval"
      ? "Needs approval"
      : phase === "working"
        ? "Working"
        : phase === "blocked"
          ? "Blocked"
          : phase === "loading"
            ? "Connecting"
            : phase === "intake"
              ? "Drafting"
              : "Needs input";

  return (
    <div className="conversation-workspace">
      <aside aria-label="Task conversations" className="conversation-sidebar">
        <button className="new-task-button" onClick={restart} type="button">＋ <span>New task</span></button>
        <div className="sidebar-label">Today</div>
        <button aria-current="page" className="thread-row active" type="button">
          <span>Lower my mobile bill</span>
          <small>{status}</small>
        </button>
        <p className="sidebar-boundary">One fictional telecom journey. The Runtime is local and process-bound.</p>
      </aside>

      <section aria-labelledby="conversation-title" className="conversation-panel">
        <header className="conversation-header">
          <div>
            <span className="conversation-overline">Fictional telecom task</span>
            <h1 id="conversation-title">Lower my mobile bill</h1>
          </div>
          <StatusBadge tone={phase === "receipt" ? "complete" : phase === "blocked" ? "blocked" : phase === "working" ? "working" : "neutral"}>{status}</StatusBadge>
        </header>

        <div aria-live="polite" aria-relevant="additions" className="conversation-thread" role="log">
          <AssistantMessage>
            <p>I can help with that. Tell me the outcome you want, and I&apos;ll ask only for details that change the plan or authorization.</p>
          </AssistantMessage>

          {messages.map((message) => message.role === "user"
            ? <UserMessage key={message.id}><p>{message.text}</p></UserMessage>
            : <AssistantMessage key={message.id}><p>{message.text}</p></AssistantMessage>)}

          {(phase === "intake" || phase === "loading") ? (
            <AssistantMessage>
              <DraftTaskBrief
                activeField={activeField}
                busy={busy}
                draft={intake}
                intakeError={intakeError}
                onCreate={createIntakeCase}
                onEdit={editIntakeField}
              />
            </AssistantMessage>
          ) : null}

          {payload && (phase === "confirm" || phase === "working" || phase === "approval" || phase === "receipt" || phase === "blocked") ? (
            <AssistantMessage><TaskBriefArtifact payload={payload} onConfirm={phase === "confirm" && !busy ? confirmConstraint : undefined} /></AssistantMessage>
          ) : null}

          {payload && phase === "working" ? <AssistantMessage><ProgressArtifact /></AssistantMessage> : null}

          {payload && (phase === "approval" || phase === "receipt") ? (
            <AssistantMessage>
              <p>The Runtime returned one offer that satisfies the confirmed guardrails. Nothing is accepted until you approve the exact request.</p>
              <OfferArtifact payload={payload} />
              {phase === "approval" ? <ApprovalArtifact busy={busy} onApprove={approveExactTerms} payload={payload} /> : null}
            </AssistantMessage>
          ) : null}

          {intakeError ? (
            <AssistantMessage>
              <section aria-live="polite" className="intake-inline-error" role="alert">
                <strong>Draft stays local</strong>
                <p>{intakeError}</p>
              </section>
            </AssistantMessage>
          ) : null}
          {payload && phase === "receipt" ? <AssistantMessage><ReceiptArtifact payload={payload} /></AssistantMessage> : null}
          {error ? <AssistantMessage><RuntimeErrorState error={error} onRestart={restart} /></AssistantMessage> : null}
        </div>

        <form className="conversation-composer" onSubmit={submitMessage}>
          <label className="sr-only" htmlFor="conversation-message">Message ProxyLoop</label>
          <textarea
            disabled={phase === "loading" || busy}
            id="conversation-message"
            onChange={(event) => setDraft(event.target.value)}
            placeholder={phase === "loading" ? "Connecting to local Runtime…" : "Message ProxyLoop"}
            rows={1}
            value={draft}
          />
          <button aria-label="Send message" className="composer-send" disabled={!draft.trim() || phase === "loading" || busy} type="submit">→</button>
          <p>One local fictional Case · no upload · no external model</p>
        </form>
      </section>

      <aside aria-label="Current task context" className="context-rail">
        <div className="context-section">
          <span className="context-label">Current goal</span>
          <strong>{payload ? formatMoney(objectAt(goalRecord(payload), "target_monthly_total")) : "Runtime snapshot pending"}</strong>
          <p>Lower the monthly total while preserving the returned hard constraints.</p>
        </div>
        <div className="context-section">
          <span className="context-label">Known facts</span>
          <dl>
            <div><dt>Current</dt><dd>{payload ? formatMoney(objectAt(billRecord(payload), "monthly_total")) : "—"}</dd></div>
            <div><dt>Usage</dt><dd>{payload ? (stringAt(objectAt(billRecord(payload), "usage"), "data_gb") ?? "Runtime fact") : "—"}</dd></div>
            <div><dt>Case revision</dt><dd>{payload?.revision ?? "—"}</dd></div>
          </dl>
        </div>
        <div className="context-section">
          <span className="context-label">Authority</span>
          <p><span aria-hidden="true" className="shield-mark">◇</span>Accepting an offer always requires exact approval pins from the Runtime.</p>
        </div>
        <p className="context-detail-link">Conversation is the primary workspace.</p>
      </aside>
    </div>
  );
}
