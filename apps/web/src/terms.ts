// An offer's terms as the approval card shows them (redesign §3.2): Guard's
// offer.recorded slots turned into plain rows, with money in minor units and
// times of day. Display only: no arithmetic on money (AGENTS rule 13), and a
// time is never compared with the client clock.
import { readback, type ApprovalCard } from "./approval";
import { from } from "./authority";
import type { Ev } from "./replay";

function field(value: unknown, key: string): unknown {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)[key]
    : undefined;
}

// Ported from v0 (apps/web/lib/format.ts).
// null when the value is not a projected Money (integer minor units + currency).
export function formatMoneyOrNull(value: unknown): string | null {
  const amountMinor = field(value, "amount_minor");
  const currency = field(value, "currency");
  if (typeof amountMinor !== "number" || !Number.isInteger(amountMinor)) return null;
  if (typeof currency !== "string" || !currency.trim()) return null;
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

/** Minor units (a number or Guard's digit string) as dollars; null if it is not whole cents. */
export const usd = (minor: unknown): string | null =>
  formatMoneyOrNull({ amount_minor: typeof minor === "string" && /^\d+$/.test(minor) ? Number(minor) : minor, currency: "USD" });

/** "$78.00" → "$78" for a headline; any other amount as it is. */
export const whole = (money: string) => money.replace(/\.00$/, "");

const at = (iso: string, opts: Intl.DateTimeFormatOptions): string | null => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString("en-US", opts);
};
/** A time of day in the viewer's zone ("2:39 PM"), or null. */
export const clock = (iso: unknown) => (typeof iso === "string" ? at(iso, { hour: "numeric", minute: "2-digit" }) : null);
const dateTime = (iso: string) => at(iso, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** A kernel-clock time (t_ms since session.started) as "about 2:39 PM"; static, display only. */
export function aboutClock(events: Ev[], tMs: number): string | null {
  const start = events.find((e) => from(e, "session.started", ["kernel"]));
  const t0 = start?.wall ? new Date(start.wall).getTime() : NaN;
  if (Number.isNaN(t0) || !Number.isFinite(tMs)) return null;
  const t = clock(new Date(t0 + tMs).toISOString());
  return t && `about ${t}`;
}

/** contract/state.py ReadbackSlot, as offer.recorded carries it. */
export type OfferSlot = { field: string; value: string; unit: string; status?: string; source_utt?: string | null };

/** The card's own terms: Guard's offer.recorded for its offer revision (its terms_hash must match when set). */
export function offerSlots(events: Ev[], card: ApprovalCard): OfferSlot[] | null {
  const rec = events.findLast(
    (e) =>
      from(e, "offer.recorded", ["guard"]) &&
      e.payload.offer_ref === card.offer_ref &&
      e.payload.revision === card.revision &&
      (e.payload.terms_hash == null || e.payload.terms_hash === card.terms_hash),
  );
  return Array.isArray(rec?.payload.slots) ? (rec.payload.slots as OfferSlot[]) : null;
}

const LABEL: Record<string, string> = {
  monthly_price: "Monthly price",
  term_months: "Contract length",
  fees_none: "One-time fees",
  changes_none: "Changes to your plan",
  expires: "Offer valid until",
  fee: "Fee",
  credit: "Credit",
  applied_change: "Plan change",
  feature: "Includes",
};
const NONE: Record<string, string> = { true: "None", false: "Yes" };

/** One slot as [label, value]; an unknown field or value is shown as sent. */
export function termRow(name: string, value: string | undefined): [string, string] {
  const v = value ?? "";
  const [kind = name, code] = name.split(/:(.*)/s);
  const label = LABEL[kind] ?? name;
  if (kind === "monthly_price") return [label, usd(v) ?? v];
  if (kind === "fee" || kind === "credit") return [`${label}: ${code}`, usd(v) ?? v];
  // Booleans (guard/terms.py): a false one is never shown as included.
  if (kind === "applied_change" || kind === "feature") return [v !== "false" ? label : kind === "feature" ? "Not included" : "No plan change", code ?? v];
  if (kind === "term_months") return [label, v && `${v} months`];
  if (kind === "expires") return [label, v === "none" ? "No expiry" : ((v && dateTime(v)) ?? v)];
  if (kind === "fees_none" || kind === "changes_none") return [label, NONE[v] ?? v];
  return [label, v];
}

export type TermRow = { field: string; label: string; value: string; status: string };

/** The card's rows: Guard's latest read-back of its revision, valued from offer.recorded. */
export function termRows(events: Ev[], card: ApprovalCard): TermRow[] {
  const offer = offerSlots(events, card) ?? [];
  const slots = readback(events, card) ?? offer.map((s) => ({ field: s.field, status: s.status ?? "unknown" }));
  return slots.map(({ field, status }) => {
    const [label, value] = termRow(field, offer.find((s) => s.field === field)?.value);
    return { field, label, value, status };
  });
}

export const READBACK_CHIP: Record<string, string> = {
  confirmed: "Read back",
  heard: "Heard, not read back",
  unknown: "Not stated",
};
