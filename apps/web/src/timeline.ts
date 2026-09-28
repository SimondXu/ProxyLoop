// The rail (redesign §3.2 AgentRail): the steps the case took, the status
// line's one sentence and the planner's pulse. Pure, from fixed-emitter events
// with an actor check; an event from any other actor moves nothing. It reads
// only PAYLOAD_KEYS: never text_generated, an s2f text or a summary's text
// (I5), and it never credits a grant that did not happen (I6): "said" needs the
// kernel's delivery of the same generation, not just the voice's s2f.voiced,
// and the yes names no approver yet.
import type { CardView } from "./approval";
import { from } from "./authority";
import { callHead } from "./conversation";
import * as C from "./copy";
import { PROGRESS } from "./decision";
import type { MandateView } from "./mandate";
import { statusView, statusWords } from "./outcome";
import type { Ev } from "./replay";
import { termRows, usd, whole } from "./terms";

/** Every payload key the rail may read (nested ones dotted, array items as []). */
export const PAYLOAD_KEYS = [
  "lane", "type", "guide", "guide.move", "msg_id", "gen_id", "op", "fence_id", "utt_id", "reason", "new", "call",
  "kind", "cap_id", "capability", "capability.cap_id", "capability.terms_hash", "capability.epoch", "intent",
  "offer_ref", "revision", "slots", "slots[].field", "slots[].value", "slots[].status", "slot_statuses", "terms_hash",
  "approval_id", "authority_epoch", "decision", "by", "confirmation_id", "verdict", "reasons", "status", "interrupted",
  "models",
] as const;
type Key = (typeof PAYLOAD_KEYS)[number];

const get = (e: Ev, k: Key): unknown => e.payload[k];
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const field = (v: unknown, k: string): unknown => (typeof v === "object" && v !== null ? (v as Record<string, unknown>)[k] : undefined);

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
  const voiced = new Map<string, string>(); // msg_id → "lane:gen_id", as the voice claims
  const delivered = new Set<string>(); // "lane:gen_id" the kernel delivered
  const userMsgs = new Set<string>();
  const approvals = new Map<string, number>(); // undecided approval_id → its card epoch
  const accepts = new Set<string>(); // cap_ids authorized, neither released nor revoked
  let calls = 0;
  let open = false;
  let limits = false; // a granted mandate in force
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
      voiced.set(str(get(e, "msg_id")), `${e.actor.slice("fast.".length)}:${str(get(e, "gen_id"))}`);
    } else if (from(e, "utt.delivered", ["kernel"])) {
      const sentence = cause(e, "fast.sentence", [`fast.${lane}`]);
      if (sentence) delivered.add(`${lane}:${str(get(sentence, "gen_id"))}`);
      const released = cause(e, "speak.released", ["kernel"]);
      const line = released && cause(released, "speak.verbatim", ["guard"]);
      const kind = line ? str(get(line, "kind")) : "";
      if (kind === "disclosure") add(e, C.WHO.guard, C.STEP.disclosure, "guard");
      else if (kind === "accept") add(e, C.WHO.phone, get(e, "interrupted") === true ? C.STEP.saidYesCut : C.STEP.saidYes, "voice");
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
      const granted = get(e, "decision") === "granted";
      limits = granted;
      add(e, get(e, "by") === "ui" ? C.WHO.you : C.WHO.sim, C.limitsDecided(granted), "you");
    } else if (from(e, "authority.epoch", ["kernel", "guard"])) {
      epoch = Number(get(e, "new"));
      const reason = str(get(e, "reason"));
      if (reason === "mandate_decided") continue;
      limits = false;
      const { who, text } = C.epochText(reason);
      add(e, who, text, who === C.WHO.you ? "you" : "planner");
    } else if (from(e, "offer.recorded", ["guard"])) {
      const slots = get(e, "slots");
      const slot = (f: string) => (Array.isArray(slots) ? slots.find((s) => field(s, "field") === f) : undefined);
      const price = usd(field(slot("monthly_price"), "value"));
      const months = str(field(slot("term_months"), "value")) || null;
      const rev = Number(get(e, "revision"));
      add(e, C.WHO.offer, C.offerText(price, months, rev), "offer", `offer:${str(get(e, "offer_ref"))}:${rev}`);
    } else if (from(e, "readback.updated", ["guard"])) {
      const st = get(e, "slot_statuses");
      const all = typeof st === "object" && st !== null ? Object.values(st) : [];
      const text = C.readbackText(all.filter((s) => s === "confirmed").length, all.length);
      add(e, C.WHO.guard, text, "guard", `readback:${str(get(e, "offer_ref"))}:${String(get(e, "revision"))}`);
    } else if (from(e, "approval.requested", ["guard"])) {
      approvals.set(str(get(e, "approval_id")), Number(get(e, "authority_epoch")));
      add(e, C.WHO.guard, C.STEP.askedApproval + (limits ? C.STEP.outsideLimits : ""), "guard");
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
      // Attribution gap, on purpose: no grant is named until S1-SYS-51's grantOfAccept is wired here.
      add(e, C.WHO.guard, C.CLEARED, "guard");
    } else if (from(e, "speak.released", ["kernel"]) || from(e, "speak.revoked", ["kernel"])) {
      const line = cause(e, "speak.verbatim", ["guard"]);
      if (!line || get(line, "kind") !== "accept") continue;
      accepts.delete(str(get(line, "cap_id")));
      if (e.type === "speak.revoked") add(e, C.WHO.guard, C.stoppedYes(str(get(e, "reason"))), "guard");
    } else if (from(e, "screen.redacted", ["guard"]) || from(e, "declass.denied", ["guard"])) add(e, C.WHO.guard, C.STEP.kept, "guard");
    else if (from(e, "action.denied", ["guard"]) && str(get(e, "intent")) in C.DENIED) {
      add(e, C.WHO.guard, C.blocked(str(get(e, "intent")), str(get(e, "reason"))), "guard");
    } else if (from(e, "evidence.recorded", ["guard"])) add(e, C.WHO.guard, C.confirmation(str(get(e, "confirmation_id"))), "guard");
    else if (from(e, "completion.decided", ["guard"])) {
      add(e, C.WHO.guard, get(e, "verdict") === "ok" ? C.STEP.verified : C.STEP.notVerified, "guard");
    }
  }
  for (const m of marks) {
    const gen = voiced.get(m.msg);
    const said = gen !== undefined && gen.startsWith(`${m.lane}:`) && delivered.has(gen);
    const step = steps[at.get(m.key) ?? -1];
    if (step) step.mark = said ? C.said(m.lane) : C.PASSED;
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
  if (outcome) return outcome.title;
  const card = cards.findLast((v) => v.status === "open");
  if (card) return C.NOW.approve(cardTerms(events, card));
  if (mandates.some((v) => v.status === "open")) return C.NOW.limits;
  const ask = steps.findLast((s) => s.kind === "ASK_USER");
  const replied = (seq: number) => events.some((e) => from(e, "user.msg", ["kernel"]) && e.seq > seq);
  if (ask && ask.mark !== C.PASSED && !replied(ask.seq)) return C.NOW.reply;
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
