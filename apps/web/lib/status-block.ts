import { formatMoneyOrNull as money } from "./format";
import {
  completionHasVerifiedEvidence,
  type JsonObject,
  phaseForPayload,
  type RuntimePayload,
} from "./runtime-client";

// The Agent Status Bar (PR-10): a deterministic rendering of the allow-listed
// browser projection for the person reading the Case. This is the only place
// its text is built. It reads no clock and no per-command model echo, and it is
// never a model prompt (PR-8 I12): no Runtime or ML module can import it.
// The activity line follows the workspace's own classification
// (`phaseForPayload`), so the bar never describes a state the rest of the Web
// refuses to show.

export type StatusRow = { label: string; value: string };
export type StatusBlock = { doingNow: string; asOf: string; rows: StatusRow[] };

// `blocked`: the workspace itself is Blocked (a rejected read, a mismatched
// Case, a sticky block). The payload it still holds is then not verified.
// `awaitingConsumer`: the workspace is waiting for the consumer to confirm the
// Task Brief (its confirm phase), so nothing is being planned yet.
export type StatusBlockOptions = { blocked?: boolean; awaitingConsumer?: boolean };

const NOT_VERIFIED = "Stopped — state not verified. Reconnect or restart the local demo.";

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function objectAt(value: unknown, key: string): JsonObject | null {
  const child = isObject(value) ? value[key] : undefined;
  return isObject(child) ? child : null;
}

function arrayAt(value: unknown, key: string): unknown[] {
  const child = isObject(value) ? value[key] : undefined;
  return Array.isArray(child) ? child : [];
}

function stringAt(value: unknown, key: string): string | null {
  const child = isObject(value) ? value[key] : undefined;
  return typeof child === "string" && child.trim() ? child : null;
}

function integerAt(value: unknown, key: string): number | null {
  const child = isObject(value) ? value[key] : undefined;
  return typeof child === "number" && Number.isInteger(child) ? child : null;
}

function humanize(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function strings(value: unknown[]): string[] {
  return value.filter((item): item is string => typeof item === "string" && item.trim() !== "");
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function doingNow(payload: RuntimePayload, phase: string | null, options: StatusBlockOptions): string {
  if (options.blocked) return NOT_VERIFIED;
  const view = phaseForPayload(payload);
  if (view === "blocked") return NOT_VERIFIED;
  if (view === "receipt") return "Done: the Runtime verified completion against Provider Evidence.";
  if (view === "expired") return "Stopped: the approval expired and nothing was accepted.";
  if (view === "finalizing") {
    // Same condition as the Progress artifact title (M-4).
    return payload.approval?.decision === "approved"
      ? "Executing the approved fictional transition; waiting for a verified result."
      : "Finalizing the fictional transition; waiting for a verified result.";
  }
  if (view === "approval") return "Waiting for your approval of the exact terms.";
  if (options.awaitingConsumer) return "Waiting for you to confirm the Task Brief.";
  if (phase === "initiated" || phase === "strategy") return "Planning from your confirmed goal.";
  if (phase === "negotiating") return "Negotiating with the fictional Provider.";
  if (phase === null) return "Waiting for the Runtime to report the Case phase.";
  return "Waiting for the Runtime.";
}

function goal(currentCase: JsonObject | null): string {
  const target = money(objectAt(objectAt(currentCase, "goal"), "target_monthly_total"));
  if (target === null) return "Not reported";
  const bill = money(objectAt(objectAt(currentCase, "bill_snapshot"), "monthly_total"));
  const deadline = stringAt(objectAt(currentCase, "goal"), "deadline");
  return [
    `${target} or below per month${bill === null ? "" : ` (current bill ${bill})`}`,
    ...(deadline === null ? [] : [`by ${deadline}`]),
  ].join(" · ");
}

function constraints(currentCase: JsonObject | null): string {
  const currentGoal = objectAt(currentCase, "goal");
  const keep = strings(arrayAt(currentGoal, "required_features")).map(humanize);
  const never = strings(arrayAt(currentGoal, "forbidden_changes")).map(humanize);
  const parts = [
    ...(keep.length ? [`Keep: ${keep.join(", ")}`] : []),
    ...(never.length ? [`Never change: ${never.join(", ")}`] : []),
    ...arrayAt(currentCase, "constraints").flatMap((item) => {
      const classification = stringAt(item, "classification");
      const statement = stringAt(item, "statement");
      return classification && statement ? [`${humanize(classification)}: ${statement}`] : [];
    }),
  ];
  return parts.length ? parts.join(" · ") : "None reported";
}

function currentOffer(payload: RuntimePayload): string {
  const offer = arrayAt(payload.snapshot, "offers")[0];
  if (!isObject(offer)) return "No offer yet";
  const monthly = money(offer.monthly_price);
  const total = money(offer.total_cost);
  const term = integerAt(offer, "term_months");
  const features = strings(arrayAt(offer, "features")).map(humanize);
  const expires = stringAt(offer, "expires_at");
  const revision = integerAt(offer, "revision");
  const fees = Array.isArray(offer.fees)
    ? offer.fees.flatMap((fee) => {
      const name = stringAt(fee, "name");
      const amount = money(objectAt(fee, "amount"));
      return name && amount ? [`${humanize(name)} ${amount}`] : [];
    })
    : null;
  return [
    // Same wording as the Offer artifact when the Provider is not named.
    stringAt(offer, "provider_id") ?? "Fictional Provider",
    ...(monthly === null ? [] : [`${monthly}/month`]),
    ...(total === null ? [] : [`total ${total}`]),
    ...(fees === null ? [] : [fees.length ? `fees: ${fees.join(", ")}` : "no fees"]),
    ...(term === null ? [] : [`${term} months`]),
    ...(features.length ? [features.join(", ")] : []),
    ...(expires === null ? [] : [`offer expires ${expires}`]),
    ...(revision === null ? [] : [`offer revision ${revision}`]),
  ].join(" · ");
}

function approval(payload: RuntimePayload): string {
  const current = payload.approval;
  if (current === null) return "None";
  const decision = nonEmpty(current.decision);
  if (decision === null) return "Not reported";
  const expires = stringAt(current, "expires_at");
  if (decision === "pending") return `Pending · expires ${expires ?? "time not reported"}`;
  if (decision === "expired") return expires ? `Expired at ${expires}` : "Expired";
  return humanize(decision);
}

function execution(payload: RuntimePayload): string {
  if (payload.snapshot.pending_execution === true) return "In progress";
  const count = payload.execution_count;
  if (count === 0) return "Not started";
  return `Executed ${count} ${count === 1 ? "time" : "times"}`;
}

function completion(payload: RuntimePayload): string {
  const decision = nonEmpty(payload.completion.decision);
  if (decision === null) return "Not reported";
  if (decision === "complete") {
    if (!completionHasVerifiedEvidence(payload)) {
      return "Complete claimed without matching Evidence · no receipt";
    }
    const count = Array.isArray(payload.completion.evidence_ids) ? payload.completion.evidence_ids.length : 0;
    return `Verified complete · ${count} matching Evidence ${count === 1 ? "ID" : "IDs"} · receipt shown`;
  }
  const reasons = strings(Array.isArray(payload.completion.reason_codes) ? payload.completion.reason_codes : [])
    .map(humanize);
  return [humanize(decision), ...(reasons.length ? [reasons.join(", ")] : [])].join(" · ");
}

export function renderStatusBlock(
  payload: RuntimePayload,
  options: StatusBlockOptions = {},
): StatusBlock {
  const currentCase = objectAt(payload.snapshot, "case");
  const phase = nonEmpty(payload.snapshot.phase);
  return {
    doingNow: doingNow(payload, phase, options),
    asOf: `as of Case revision ${payload.revision}`,
    rows: [
      { label: "Phase", value: phase === null ? "Not reported" : humanize(phase) },
      { label: "Goal", value: goal(currentCase) },
      { label: "Constraints", value: constraints(currentCase) },
      { label: "Current offer", value: currentOffer(payload) },
      { label: "Approval", value: approval(payload) },
      { label: "Execution", value: execution(payload) },
      { label: "Completion", value: completion(payload) },
    ],
  };
}
