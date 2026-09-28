// The rail (redesign §3.2 AgentRail): the steps the case took, the status
// line's one sentence and the planner's pulse. Pure, from fixed-emitter events
// with an actor check; an event from any other actor moves nothing. It reads
// only PAYLOAD_KEYS: never text_generated, an s2f text or a summary's text
// (I5), and it never credits a grant that did not happen (I6): "said" needs the
// kernel's delivery of the same generation, not just the voice's s2f.voiced,
// and the yes names an approver only on the approval grant Guard cites.
import type { CardView } from "./approval";
import { from } from "./authority";
import { callHead, grantOfAccept } from "./conversation";
import * as C from "./copy";
import { approvalStatusText, PROGRESS } from "./decision";
import type { MandateView } from "./mandate";
import { receiptKind, receiptTitle, statusView, statusWords, VERIFIED_AGAINST } from "./outcome";
import type { Ev } from "./replay";
import { termRows, usd, whole } from "./terms";

/** Every payload key the rail may read (nested ones dotted, array items as []). */
export const PAYLOAD_KEYS = [
  "lane", "type", "guide", "guide.move", "msg_id", "gen_id", "op", "fence_id", "utt_id", "reason", "new", "call",
  "kind", "cap_id", "capability", "capability.cap_id", "capability.terms_hash", "capability.epoch", "intent",
  "offer_ref", "revision", "slots", "slots[].field", "slots[].value", "slots[].status", "slot_statuses", "terms_hash",
  "approval_id", "authority_epoch", "decision", "by", "confirmation_id", "verdict", "reasons", "status", "interrupted",
  "models", "name", "args", "args.offer_ref",
  "text_heard", // only whether it is empty (heard()): a cut-off line is not "said"; never shown
] as const;
type Key = (typeof PAYLOAD_KEYS)[number];

const get = (e: Ev, k: Key): unknown => e.payload[k];
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const field = (v: unknown, k: string): unknown => (typeof v === "object" && v !== null ? (v as Record<string, unknown>)[k] : undefined);
/** A delivery as heard: whole, cut off after some words, or cut off before any. */
type Heard = "whole" | "partial" | "none";
const heard = (e: Ev): Heard => (get(e, "interrupted") === false ? "whole" : str(get(e, "text_heard")) ? "partial" : "none");
const RANK: Record<Heard, number> = { none: 0, partial: 1, whole: 2 };

export type StepIcon = "planner" | "voice" | "you" | "call" | "guard" | "hold" | "offer";
/** One step. `kind`: the s2f type for a planner message, else the event type. `mark`: said or only passed on. */
export type Step = { key: string; seq: number; t_ms: number; group: string; kind: string; who: string; text: string; icon: StepIcon; mark: string | null };

const S2F: Record<string, { who: string; icon: StepIcon }> = {
  ASK_USER: { who: C.WHO.planner, icon: "planner" },
  TELL_USER: { who: C.WHO.planner, icon: "planner" },
  GUIDE: { who: C.WHO.toVoice, icon: "voice" },
};
const FAST = ["fast.user", "fast.cp"];

export function timeline(events: Ev[]): Step[] {
  const byId = new Map(events.map((e) => [e.event_id, e]));
  const steps: Step[] = [];
  const at = new Map<string, number>(); // a merged step's key → its index
  const marks: { key: string; msg: string; lane: string }[] = [];
  const voiced = new Map<string, Set<string>>(); // msg_id → every "lane:gen_id" the voice claims it in
  const delivered = new Map<string, Heard>(); // "lane:gen_id" → the best the kernel delivered of it
  const outside = new Set<string>(); // "offer_ref:revision" Guard refused to accept as outside_mandate
  const revisions = new Map<string, number>(); // offer_ref → its latest recorded revision
  const userMsgs = new Set<string>();
  const approvals = new Map<string, number>(); // undecided approval_id → its card epoch
  const accepts = new Set<string>(); // cap_ids authorized, neither released nor revoked
  let calls = 0;
  let open = false;
  let epoch = 0;
  const group = () => (calls === 0 ? C.GROUP.before : open ? C.callGroup(calls) : C.GROUP.after);
  const add = (e: Ev, who: string, text: string, icon: StepIcon, key = String(e.seq), kind = e.type) => {
    const merged = steps[at.get(key) ?? -1];
    if (merged) Object.assign(merged, { t_ms: e.t_ms, text });
    else {
      at.set(key, steps.length);
      steps.push({ key, seq: e.seq, t_ms: e.t_ms, group: group(), kind, who, text, icon, mark: null });
    }
  };
  const cause = (e: Ev, type: string, actors: string[]) =>
    e.cause_ids.map((id) => byId.get(id)).find((c): c is Ev => c !== undefined && from(c, type, actors));

  for (const e of events) {
    const lane = str(get(e, "lane"));
    if (from(e, "user.msg", ["kernel"])) userMsgs.add(e.event_id);
    else if (from(e, "s2f.msg", ["guard"])) {
      const type = str(get(e, "type"));
      const s = S2F[type];
      if (!s) continue;
      const move = str(field(get(e, "guide"), "move"));
      const text = type === "GUIDE" ? (C.MOVE[move] ?? move) : type === "ASK_USER" ? C.STEP.asked : C.STEP.told;
      add(e, s.who, text, s.icon, String(e.seq), type);
      marks.push({ key: String(e.seq), msg: str(get(e, "msg_id")), lane });
    } else if (e.type === "s2f.voiced" && FAST.includes(e.actor)) {
      const gen = str(get(e, "gen_id"));
      const msg = str(get(e, "msg_id"));
      if (gen) voiced.set(msg, (voiced.get(msg) ?? new Set()).add(`${e.actor.slice("fast.".length)}:${gen}`));
    } else if (from(e, "utt.delivered", ["kernel"])) {
      const sentence = cause(e, "fast.sentence", [`fast.${lane}`]);
      const gen = sentence ? str(get(sentence, "gen_id")) : "";
      const was = delivered.get(`${lane}:${gen}`);
      if (gen && (was === undefined || RANK[heard(e)] > RANK[was])) delivered.set(`${lane}:${gen}`, heard(e));
      const released = cause(e, "speak.released", ["kernel"]);
      const line = released && cause(released, "speak.verbatim", ["guard"]);
      const kind = line ? str(get(line, "kind")) : "";
      if (kind === "disclosure") add(e, C.WHO.guard, C.STEP.disclosure, "guard");
      else if (kind === "accept") add(e, C.WHO.phone, C.SAID_YES[heard(e)], "voice");
    } else if (from(e, "chan.opened", ["kernel"]) && lane === "cp") {
      const n = get(e, "call");
      calls = typeof n === "number" ? n : calls + 1;
      open = true;
      add(e, C.WHO.call, calls > 1 ? C.STEP.calledBack : C.STEP.called, "call");
    } else if (from(e, "chan.closed", ["kernel"]) && lane === "cp") {
      add(e, C.WHO.call, C.STEP.callEnded, "call");
      open = false;
    } else if (from(e, "chan.hold", ["fast.cp"]) && get(e, "reason") != null) add(e, C.WHO.phone, C.STEP.hold, "hold");
    else if (from(e, "mandate.proposed", ["guard"])) add(e, C.WHO.planner, C.STEP.proposed, "planner");
    else if (from(e, "mandate.decided", ["kernel"])) {
      if (get(e, "decision") === "granted") outside.clear(); // new limits: an old refusal says nothing about them
      add(e, get(e, "by") === "ui" ? C.WHO.you : C.WHO.sim, C.limitsDecided(get(e, "decision") === "granted"), "you");
    } else if (from(e, "authority.epoch", ["kernel", "guard"])) {
      epoch = Number(get(e, "new"));
      const reason = str(get(e, "reason"));
      if (reason === "mandate_decided") continue;
      const { who, text } = C.epochText(reason);
      add(e, who, text, who === C.WHO.you ? "you" : "planner");
    } else if (from(e, "offer.recorded", ["guard"])) {
      const slots = get(e, "slots");
      const slot = (f: string) => (Array.isArray(slots) ? slots.find((s) => field(s, "field") === f) : undefined);
      const price = usd(field(slot("monthly_price"), "value"));
      const months = str(field(slot("term_months"), "value")) || null;
      const rev = Number(get(e, "revision"));
      revisions.set(str(get(e, "offer_ref")), rev);
      add(e, C.WHO.offer, C.offerText(price, months, rev), "offer", `offer:${str(get(e, "offer_ref"))}:${rev}`);
    } else if (from(e, "readback.updated", ["guard"])) {
      const st = get(e, "slot_statuses");
      const all = typeof st === "object" && st !== null ? Object.values(st) : [];
      const text = C.readbackText(all.filter((s) => s === "confirmed").length, all.length);
      add(e, C.WHO.guard, text, "guard", `readback:${str(get(e, "offer_ref"))}:${String(get(e, "revision"))}`);
    } else if (from(e, "approval.requested", ["guard"])) {
      approvals.set(str(get(e, "approval_id")), Number(get(e, "authority_epoch")));
      // "outside your limits" only on Guard's word: its outside_mandate refusal of this offer's accept.
      add(e, C.WHO.guard, C.STEP.askedApproval + (outside.has(`${str(get(e, "offer_ref"))}:${Number(get(e, "revision"))}`) ? C.STEP.outsideLimits : ""), "guard");
    } else if (from(e, "approval.decided", ["kernel"])) {
      approvals.delete(str(get(e, "approval_id")));
      add(e, get(e, "by") === "ui" ? C.WHO.you : C.WHO.sim, C.approvalDecided(get(e, "decision") === "granted"), "you");
    } else if (from(e, "authority.fence", ["kernel", "guard"])) {
      const key = `fence:${str(get(e, "fence_id"))}`;
      const pending = [...approvals.values()].some((ep) => ep >= epoch) || accepts.size > 0;
      if (get(e, "op") === "raised" && userMsgs.has(str(get(e, "utt_id"))) && pending) add(e, C.WHO.you, C.STEP.paused, "you", key);
      else if (get(e, "op") === "cleared" && at.has(key)) add(e, C.WHO.you, C.STEP.pausedRead, "you", key);
    } else if (from(e, "action.authorized", ["guard"]) && get(e, "intent") === "accept_offer") {
      const cap = str(field(get(e, "capability"), "cap_id"));
      accepts.add(cap);
      // The kernel's approval grant behind this accept (conversation.ts); none (e.g. under limits) names no one.
      const line = events.find((v) => from(v, "speak.verbatim", ["guard"]) && get(v, "kind") === "accept" && get(v, "cap_id") === cap);
      const grant = line ? grantOfAccept(line, events) : null; // a mandate's grant names no approver
      add(e, C.WHO.guard, C.cleared(grant?.type === "approval.decided" ? str(get(grant, "by")) : null), "guard");
    } else if (from(e, "speak.released", ["kernel"]) || from(e, "speak.revoked", ["kernel"])) {
      const line = cause(e, "speak.verbatim", ["guard"]);
      if (!line || get(line, "kind") !== "accept") continue;
      accepts.delete(str(get(line, "cap_id")));
      if (e.type === "speak.revoked") add(e, C.WHO.guard, C.stoppedYes(str(get(e, "reason"))), "guard");
    } else if (from(e, "screen.redacted", ["guard"]) || from(e, "declass.denied", ["guard"])) add(e, C.WHO.guard, C.STEP.kept, "guard");
    else if (from(e, "action.denied", ["guard"]) && str(get(e, "intent")) in C.DENIED) {
      const tool = cause(e, "slow.tool", ["slow"]); // the refused call: which offer
      const ref = tool && get(tool, "name") === "accept_offer" ? str(field(get(tool, "args"), "offer_ref")) : "";
      if (get(e, "intent") === "accept_offer" && get(e, "reason") === "outside_mandate" && revisions.has(ref)) outside.add(`${ref}:${revisions.get(ref)}`);
      add(e, C.WHO.guard, C.blocked(str(get(e, "intent")), str(get(e, "reason"))), "guard");
    } else if (from(e, "evidence.recorded", ["guard"])) add(e, C.WHO.guard, C.confirmation(str(get(e, "confirmation_id"))), "guard");
    else if (from(e, "completion.decided", ["guard"])) {
      add(e, C.WHO.guard, get(e, "verdict") === "ok" ? VERIFIED_AGAINST : C.STEP.notVerified, "guard");
    }
  }
  for (const m of marks) {
    const gens = [...(voiced.get(m.msg) ?? [])].filter((g) => g.startsWith(`${m.lane}:`));
    const best = gens.map((g) => delivered.get(g)).reduce<Heard | undefined>((a, b) => (b !== undefined && (a === undefined || RANK[b] > RANK[a]) ? b : a), undefined);
    const step = steps[at.get(m.key) ?? -1];
    if (step) step.mark = best === undefined ? C.PASSED : C.said(m.lane, best);
  }
  return steps;
}

export type Group = { name: string; steps: Step[] };

/** Consecutive steps under their group's name, in order. */
export function groups(steps: Step[]): Group[] {
  const out: Group[] = [];
  for (const s of steps) {
    const last = out.at(-1);
    if (last?.name === s.group) last.steps.push(s);
    else out.push({ name: s.group, steps: [s] });
  }
  return out;
}

/** "$78/mo for 24 months", from the card's own rows (terms.ts); null without a price. */
function cardTerms(events: Ev[], v: CardView): string | null {
  const rows = termRows(events, v.card);
  const price = rows.find((r) => r.field === "monthly_price")?.value;
  const term = rows.find((r) => r.field === "term_months")?.value;
  return price ? `${whole(price)}/mo${term ? ` for ${term}` : ""}` : null;
}

/** The status line (redesign §3.2 NowCard): the first rung that holds. `cards`/`mandates` are the page's views. */
export function now(events: Ev[], steps: Step[], cards: CardView[], mandates: MandateView[]): string {
  const { outcome } = statusView(events);
  if (outcome) return receiptTitle(receiptKind(outcome), outcome); // the receipt's own title
  const card = cards.findLast((v) => v.status === "open");
  if (card) return C.NOW.approve(cardTerms(events, card));
  const answered = cards.findLast((v) => v.status === "pending" || v.status === "sent"); // after your click: never "waiting for you"
  if (answered) return approvalStatusText(answered, events);
  if (mandates.some((v) => v.status === "open")) return C.NOW.limits;
  const ask = steps.findLast((s) => s.kind === "ASK_USER");
  const replied = (seq: number) => events.some((e) => from(e, "user.msg", ["kernel"]) && e.seq > seq);
  if (ask?.mark?.startsWith("✓") && !replied(ask.seq)) return C.NOW.reply;
  const users = new Set<string>();
  const raised = new Set<string>();
  let status: string | null = null;
  for (const e of events) {
    if (from(e, "user.msg", ["kernel"])) users.add(e.event_id);
    else if (from(e, "status.changed", ["guard"])) status = str(get(e, "status"));
    else if (from(e, "authority.fence", ["kernel", "guard"])) {
      const id = str(get(e, "fence_id"));
      if (get(e, "op") === "raised" && users.has(str(get(e, "utt_id")))) raised.add(id);
      else if (get(e, "op") === "cleared") raised.delete(id);
    }
  }
  if (raised.size > 0) return C.NOW.fence;
  const progress = status === null ? undefined : PROGRESS[status];
  if (progress) return progress;
  if (callHead(events).holdSince !== null) return C.NOW.hold;
  if (status === "IN_CALL") return C.NOW.inCall;
  if (status === null || status === "INTAKE") return C.NOW.intake;
  const words = statusWords(status); // any other status, in words (an unknown one raw)
  return `${words.slice(0, 1).toUpperCase()}${words.slice(1)}`;
}

/** The planner's pulse: thinking while a step it started has not finished; null without a planner or after the end. */
export function planner(events: Ev[]): keyof typeof C.PLANNER | null {
  const start = events.find((e) => from(e, "session.started", ["kernel"]));
  const models = get(start ?? ({ payload: {} } as Ev), "models");
  if (typeof models !== "object" || models === null || !("slow" in models)) return null;
  if (events.some((e) => from(e, "session.ended", ["kernel"]))) return null;
  const done = new Set(events.filter((e) => from(e, "slow.step.completed", ["slow"])).flatMap((e) => e.cause_ids));
  return events.some((e) => from(e, "slow.step.started", ["slow"]) && !done.has(e.event_id)) ? "thinking" : "listening";
}
