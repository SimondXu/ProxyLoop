// The v4 to-do (S1-SYS-79): the case's milestones, each done, current, needs you,
// pending or not reached, and a summary tag. Pure, from fixed-emitter events through
// authority.ts `from` (a wrong actor moves nothing), reading only PAYLOAD_KEYS, its
// own reads and those of the helpers it reuses (approval.ts, mandate.ts, terms.ts,
// decision.ts, outcome.ts); never text_generated, an s2f text or a summary's text.
// It never says something happened that no event says happened, and never credits a
// grant that did not happen (I6). Generic per task kind: no family is named here.
import { approvalCards, type Posting } from "./approval";
import { from } from "./authority";
import * as C from "./copy";
import { approvalStatusText, approvedBy, lineFate, readbackCount, STOPPED } from "./decision";
import { limitsStatusText, mandateCards } from "./mandate";
import { receiptKind, receiptTitle, statusView } from "./outcome";
import type { Ev } from "./replay";
import { latestOffers, termRows, whole } from "./terms";
import type { Step } from "./timeline";

/** Every payload key the to-do may read, itself or through the helpers (nested ones dotted, array items as []). */
export const PAYLOAD_KEYS = [
  "lane", "status", "reason", "reasons", "verdict", "intent", "kind", "cap_id", "capability", "capability.cap_id",
  "mandate_id", "mandate_hash", "epoch", "decision", "by", "new", "subject", "subject_id",
  "approval_id", "offer_ref", "revision", "terms_hash", "authority_epoch", "slots", "slots[].field", "slots[].value", "slot_statuses",
] as const;

export type RowKey = "limits" | "call" | "offer" | "readback" | "decision" | "accept" | "records" | "result";
/** "noted": done, with a note that it did not go the plain way (declined, stopped, didn't match). */
export type RowState = "done" | "noted" | "current" | "needs_you" | "pending" | "not_reached";
export type TodoRow = { key: RowKey; label: string; state: RowState; note: string | null; steps: Step[] };
export type Tag = { tone: "you" | "ok" | "plain"; text: string };
export type Todo = { kind: "approval" | "info" | "unknown"; rows: TodoRow[]; other: Step[]; tag: Tag };

export const LABEL: Record<RowKey, string> = {
  limits: "Set your limits",
  call: "Call the company",
  offer: "Hear an offer",
  readback: "Have every term read back",
  decision: "Get your decision",
  accept: "Accept on the call",
  records: "Check the company's records",
  result: "Result",
};
export const NOT_REACHED = "Not reached";
export const RULE = "Checked off only when it actually happens on the call, not when the assistant says so.";
const MATCHED = "Matched the company's records";
const NOT_MATCHED = "Didn't match the company's records";
const BY_CLICK = "Approved by your click";
const SAID_YES: readonly string[] = Object.values(C.SAID_YES);
// Receipt kinds (outcome.ts) that end the case the plain way; any other is "done, with a note".
const PLAIN_END = new Set(["verified", "no_deal", "info_only"]);
const NO_POSTS: ReadonlyMap<string, Posting> = new Map();

/** A row before the pass that picks the current one: where it started (seq) and how far it got. */
type Raw = { key: RowKey; start: number | null; done: boolean; noted: boolean; you: boolean; note: string | null };

export function todo(events: Ev[], steps: Step[]): Todo {
  const guard = (e: Ev, type: string) => from(e, type, ["guard"]);
  const kernel = (e: Ev, type: string) => from(e, type, ["kernel"]);
  const first = (test: (e: Ev) => boolean) => events.find(test)?.seq ?? null;
  const accept = (e: Ev) => guard(e, "action.authorized") && e.payload.intent === "accept_offer";
  const checking = (e: Ev) => (guard(e, "status.changed") && e.payload.status === "EVIDENCE_PENDING") || guard(e, "evidence.recorded");

  const proposed = first((e) => guard(e, "mandate.proposed"));
  const requested = first((e) => guard(e, "approval.requested"));
  const called = first((e) => kernel(e, "chan.opened") && e.payload.lane === "cp");
  // Info needs a call with no limits before it; limits or a card anywhere make it an approval case.
  const kind = proposed !== null || requested !== null ? "approval" : called !== null ? "info" : "unknown";
  const end = events.find((e) => kernel(e, "session.ended"));
  const { outcome } = statusView(events);

  const raws: Raw[] = [];
  const add = (key: RowKey, start: number | null, r: Partial<Raw> = {}) =>
    raws.push({ key, start, done: false, noted: false, you: false, note: null, ...r });

  // 1. Your limits: the latest proposal's card (mandate.ts), decided only by the kernel's mandate.decided.
  if (kind === "approval") {
    const v = mandateCards(events, NO_POSTS).at(-1);
    if (!v) add("limits", null);
    else if (v.status === "denied") add("limits", proposed, { done: true, noted: true, note: C.limitsDecided(false) });
    else if (v.by !== null) add("limits", proposed, { done: true, note: limitsStatusText({ status: "granted", by: v.by, at: null, reason: null }) });
    else add("limits", proposed, { you: v.status === "open" || v.status === "sent", note: limitsStatusText(v) });
  }

  // 2. The call.
  add("call", called, { done: called !== null });

  // 3. An offer: how many Guard recorded, and the latest one's terms (terms.ts).
  const offers = latestOffers(events);
  const last = offers.at(-1);
  const rows = last ? termRows(events, last) : [];
  const heard = first((e) => guard(e, "offer.recorded"));
  const price = rows.find((r) => r.field === "monthly_price")?.value;
  const term = rows.find((r) => r.field === "term_months")?.value;
  const count = offers.length === 1 ? "1 offer heard" : `${offers.length} offers heard`;
  const latest = price ? ` · latest ${whole(price)}/mo${term ? ` for ${term}` : ""}` : "";
  add("offer", heard, { done: heard !== null, note: offers.length > 0 ? count + latest : null });

  // 4. The read-back: every row of the latest offer read back, by the approval card's own rule (terms.ts).
  const read = first((e) => guard(e, "readback.updated"));
  const all = rows.length > 0 && rows.every((r) => r.status === "confirmed");
  add("readback", read, { done: all, note: rows.length > 0 && (read !== null || all) ? readbackCount(rows) : null });

  // 5. Your decision: only once Guard asks; decided only by the kernel's approval.decided (approval.ts).
  const v = approvalCards(events, NO_POSTS).at(-1);
  if (requested !== null && v) {
    if (v.status === "granted") add("decision", requested, { done: true, note: v.by === "ui" ? BY_CLICK : approvedBy(events, v) });
    else if (v.status === "denied") add("decision", requested, { done: true, noted: true, note: C.approvalDecided(false) });
    else add("decision", requested, { you: v.status === "open" || v.status === "sent", note: approvalStatusText(v, events) });
  }

  // 6. The accept: Guard's latest accept_offer capability, its accept line, and the kernel's release or revoke of it.
  const auth = events.findLast(accept);
  if (auth || kind === "approval") {
    const cap = (auth?.payload.capability ?? {}) as { cap_id?: unknown };
    const line = auth && events.find((e) => guard(e, "speak.verbatim") && e.payload.kind === "accept" && e.payload.cap_id === cap.cap_id);
    const fate = line ? lineFate(events, line).state : null;
    const start = first(accept);
    if (fate === "revoked") add("accept", start, { done: true, noted: true, note: STOPPED });
    else if (fate === "released") {
      // How the yes was heard: the rail's own step for its delivery (timeline.ts), if it has arrived.
      const yes = steps.findLast((s) => auth !== undefined && s.seq > auth.seq && s.kind === "utt.delivered" && SAID_YES.includes(s.text))?.text ?? null;
      add("accept", start, { done: true, noted: yes === C.SAID_YES.none, note: yes });
    } else add("accept", start);
  }

  // 7. The records check: only once its events appear; the last of them says where it stands.
  const checked = first(checking);
  if (checked !== null) {
    const check = events.findLast((e) => checking(e) || guard(e, "completion.decided"));
    const ok = check?.payload.verdict === "ok";
    if (check && guard(check, "completion.decided")) add("records", checked, { done: true, noted: !ok, note: ok ? MATCHED : NOT_MATCHED });
    else add("records", checked);
  }

  // 8. The result: the receipt's own title (outcome.ts) once the kernel ends the session.
  if (end && outcome) {
    const rk = receiptKind(outcome);
    add("result", end.seq, { done: true, noted: !PLAIN_END.has(rk), note: receiptTitle(rk, outcome) });
  } else add("result", null);

  // One current row before the end: a row waiting for you, else the first not-done row from the furthest one reached.
  const waiting = raws.findIndex((r) => !r.done && r.you);
  const reached = raws.reduce((m, r, i) => (r.done || r.start !== null ? i : m), 0);
  const current = end ? -1 : waiting >= 0 ? waiting : raws.findIndex((r, i) => i >= reached && !r.done);
  const state = (r: Raw, i: number): RowState =>
    r.done ? (r.noted ? "noted" : "done") : end ? "not_reached" : i !== current ? "pending" : r.you ? "needs_you" : "current";

  // Each Step under the row that started last at or before it; before any row started, under "Other steps".
  const starts = raws.flatMap((r, i) => (r.start === null ? [] : [{ i, at: r.start }])).sort((a, b) => a.at - b.at);
  const owners = steps.map((s) => starts.findLast((x) => x.at <= s.seq)?.i ?? -1);
  const under = (i: number) => steps.filter((_s, j) => owners[j] === i);

  const out = raws.map((r, i): TodoRow => {
    const st = state(r, i);
    return { key: r.key, label: LABEL[r.key], state: st, note: st === "not_reached" ? NOT_REACHED : r.note, steps: under(i) };
  });
  const n = out.length;
  const k = out.filter((r) => r.state === "done" || r.state === "noted").length;
  const tag: Tag = out.some((r) => r.state === "needs_you")
    ? { tone: "you", text: `Needs you · ${k} of ${n} done` }
    : end && outcome?.status === "VERIFIED_COMPLETE" && k === n
      ? { tone: "ok", text: `All done · ${n} of ${n}` }
      : { tone: "plain", text: `${k} of ${n} done` };
  return { kind, rows: out, other: under(-1), tag };
}
