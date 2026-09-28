// The principal's "Your role" card (S1-SYS-65; serve.cases RoleCard): what the person playing the
// account holder knows and wants, exactly as GET /api/tasks/card or /api/cases/{case}/card sends it.
// Only the principal's own knowledge is in it (I4); nothing here adds, repairs or relabels a value.
// Display only: no arithmetic on money (AGENTS rule 13).
import { isObject } from "./liveState";

export type RoleFact = { key: string; value: string; identity: boolean; shareable: boolean };
/** What the principal would approve on a card, never a target; null: unbounded. */
export type RoleLimits = { max_monthly_price_usd: string | null; max_term_months: number | null; max_one_time_fees_usd: string | null };
export type RoleStop = { trigger: string; text_hint: string; change: Record<string, string> | null };
export type RoleCard = {
  company: string;
  persona: string;
  goal: string;
  facts: RoleFact[];
  approval: RoleLimits | null; // null: information only, nothing to approve
  stop: RoleStop | null;
};

const str = (v: unknown): v is string => typeof v === "string";
const orNull = (v: unknown, ok: (x: unknown) => boolean) => v === null || ok(v);
const isFact = (f: unknown) => isObject(f) && str(f.key) && str(f.value) && typeof f.identity === "boolean" && typeof f.shareable === "boolean";
const isLimits = (a: unknown) =>
  isObject(a) &&
  orNull(a.max_monthly_price_usd, str) &&
  orNull(a.max_term_months, Number.isInteger) &&
  orNull(a.max_one_time_fees_usd, str);
const isChange = (c: unknown) => isObject(c) && Object.values(c).every(str);
const isStop = (s: unknown) => isObject(s) && str(s.trigger) && str(s.text_hint) && orNull(s.change, isChange);

/** The card body, or why it cannot be shown. */
export function parseRoleCard(body: unknown): RoleCard | string {
  if (!isObject(body)) return "the answer is not a card";
  if (![body.company, body.persona, body.goal].every(str)) return "a card without its company, persona or goal";
  if (!Array.isArray(body.facts) || !body.facts.every(isFact)) return "a malformed fact on the card";
  if (!orNull(body.approval, isLimits)) return "malformed approval limits on the card";
  if (!orNull(body.stop, isStop)) return "a malformed stop on the card";
  return body as RoleCard;
}

/** "account.holder_name" → "Account holder name". */
export function factLabel(key: string): string {
  const words = key.split(/[._]+/).filter(Boolean).join(" ");
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

const ZERO = /^0+(\.0+)?$/;

/** The limits as rows; a bound that is null is left out (unbounded). */
export function approvalRows(a: RoleLimits): [string, string][] {
  const rows: [string, string][] = [];
  if (a.max_monthly_price_usd !== null) rows.push(["Monthly price", `up to $${a.max_monthly_price_usd}`]);
  if (a.max_term_months !== null) rows.push(["Contract", `up to ${a.max_term_months} months`]);
  const fees = a.max_one_time_fees_usd;
  if (fees !== null) rows.push(["One-time fees", ZERO.test(fees) ? "none" : `up to $${fees}`]);
  return rows;
}

/**
 * The facts as labelled rows: those the company checks (give them when asked), then every other fact you know.
 * (`shareable` is what your assistant may pass on to the company, not what you may tell your assistant.)
 */
export function factRows(facts: RoleFact[]) {
  const rows = (keep: (f: RoleFact) => boolean): [string, string][] => facts.filter(keep).map((f) => [factLabel(f.key), f.value]);
  return { identity: rows((f) => f.identity), other: rows((f) => !f.identity) };
}

const WHEN: Record<string, string> = {
  after_card: "Once you have seen an approval card",
  after_offer: "Once the company has made an offer",
  after_turn_k: "After a few messages",
};

/** When the stop is due, in words; an unknown trigger is shown raw. */
export const stopWhen = (trigger: string) => WHEN[trigger] ?? trigger;
