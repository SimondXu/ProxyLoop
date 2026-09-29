// The live page's rail (redesign §3.2 AgentRail): the status line with the
// planner's pulse, the limits in force, the to-do (v4, S1-SYS-79: todo.ts's
// milestones, each revealing its steps from timeline.ts) and how the roles work.
// Its payload reads all go through helpers: timeline.ts (steps, status line,
// planner), todo.ts (the to-do), mandate.ts's limitRows and limitsStatusText
// (the limits) and replay.ts's runHeader (the models).
import { useId, useMemo, useState } from "react";
import type { CardView } from "../approval";
import * as C from "../copy";
import { limitRows, limitsStatusText, type MandateView } from "../mandate";
import { runHeader, type Ev } from "../replay";
import { now, planner, timeline, type Step, type StepIcon } from "../timeline";
import { RULE, stateWords, todo, type RowState, type Todo } from "../todo";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Icon, type ICONS } from "../ui/Icon";
import "./rail.css";

type Props = { events: Ev[]; cards: CardView[]; mandates: MandateView[] };

export function AgentRail({ events, cards, mandates }: Props) {
  const steps = useMemo(() => timeline(events), [events]);
  const line = useMemo(() => now(events, steps, cards, mandates), [events, steps, cards, mandates]);
  const pulse = useMemo(() => planner(events), [events]);
  const list = useMemo(() => todo(events, steps), [events, steps]);
  return (
    <>
      <section className="pl-now">
        <span className="pl-label">Now</span>
        <p className="pl-now-line" role="status" aria-live="polite" aria-label="Status line">
          {line}
        </p>
        {pulse && (
          <p className={`pl-planner pl-planner-${pulse}`}>
            <span className="pl-pulse" aria-hidden="true" />
            {C.PLANNER[pulse]}
          </p>
        )}
      </section>
      <Limits mandates={mandates} />
      <ToDo t={list} />
      <HowItWorks events={events} />
    </>
  );
}

function Limits({ mandates }: { mandates: MandateView[] }) {
  const current = mandates.findLast((v) => v.status === "granted");
  return (
    <Card className="pl-rail-limits" aria-label="Your limits (summary)">
      <div className="pl-rail-row">
        <span className="pl-label">Your limits</span>
        {current && <Chip tone="ok">{limitsStatusText(current)}</Chip>}
      </div>
      {current ? (
        <ul className="pl-pills">
          {limitRows(current.mandate).map(([k, v]) => (
            <li key={k}>
              {k} {v}
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">{C.NO_LIMITS}</p>
      )}
      <p className="meta pl-rail-note">
        <Icon name="private" size="xs" />
        {C.LIMITS_NOTE}
      </p>
    </Card>
  );
}

const ICON: Record<StepIcon, keyof typeof ICONS> = { planner: "planner", voice: "voice", you: "you", call: "call", guard: "guard", hold: "hold", offer: "call" };
/** Session time, mm:ss from the run's start (t_ms). */
const mmss = (ms: number) => `${String(Math.floor(ms / 60_000)).padStart(2, "0")}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

function StepItem({ s }: { s: Step }) {
  return (
    <li className={`pl-st pl-st-${s.icon}`}>
      <span className="pl-st-ic">
        <Icon name={ICON[s.icon]} size="sm" />
      </span>
      <div>
        <p className="pl-st-who">
          {s.who} <span className="pl-st-t">{mmss(s.t_ms)}</span>
        </p>{" "}
        <p className="pl-st-x">{s.text}</p>
        {s.mark && <p className="pl-st-mark"> {s.mark}</p>}
      </div>
    </li>
  );
}

// Each state's mark (none: the ring is drawn in CSS); its words for screen readers are todo.ts stateWords.
const MARK: Record<RowState, keyof typeof ICONS | null> = {
  done: "done",
  noted: "noted",
  not_reached: "unreached",
  ended: "ended",
  current: null,
  needs_you: null,
  pending: null,
};

/** The to-do (v4 soft panel): the summary tag, one disclosure per milestone, then any steps before the first one. */
function ToDo({ t }: { t: Todo }) {
  const id = useId();
  const tag = t.tag;
  return (
    <Card className="pl-todo" aria-labelledby={id}>
      <h3 id={id} className="pl-todo-h">
        To-do
      </h3>
      <p className={`pl-todo-sum pl-todo-sum-${tag.tone}`}>
        {tag.tone === "you" && <Icon name="you" size="xs" />}
        {tag.tone === "ok" && <Icon name="done" size="xs" />}
        {tag.text}
      </p>
      <ol className="pl-todo-list" aria-label="To-do">
        {t.rows.map((r) => (
          <Milestone key={r.key} state={r.state} label={r.label} note={r.note} say={stateWords(r)} alsoYou={r.alsoYou} steps={r.steps} />
        ))}
      </ol>
      {t.other.length > 0 && (
        <ul className="pl-todo-list">
          <Milestone state="other" say="" label="Other steps" note={`${t.other.length} before the first milestone`} steps={t.other} />
        </ul>
      )}
      <p className="meta pl-todo-rule">{RULE}</p>
    </Card>
  );
}

/** One milestone: its mark, label, note and state words; a button revealing its steps when it has any. */
function Milestone(props: { state: RowState | "other"; label: string; note: string | null; say: string; alsoYou?: boolean; steps: Step[] }) {
  const { state, label, note, say, alsoYou, steps } = props;
  const [open, setOpen] = useState(false);
  const id = useId();
  const mark = state === "other" ? null : MARK[state];
  const body = (
    <>
      <span className="pl-td-g" aria-hidden="true">
        {mark && <Icon name={mark} size="xs" />}
      </span>
      <span>
        <span className="pl-td-lb">{label}</span>{" "}
        {note && (
          <span className={alsoYou ? "pl-td-nt pl-td-also" : "pl-td-nt"}>
            {alsoYou && <Icon name="you" size="xs" />}
            {note}
          </span>
        )}
        {say && <span className="pl-sr"> · {say}</span>}
      </span>
    </>
  );
  return (
    <li className={`pl-td pl-td-${state}`}>
      {steps.length > 0 ? (
        <>
          <button type="button" className="pl-td-row" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
            {body}
            <span className="pl-td-chev" aria-hidden="true">
              <Icon name="expand" size="xs" />
            </span>
          </button>
          <ol id={id} className="pl-st-list pl-td-steps" aria-label={`${label}: steps`} hidden={!open}>
            {steps.map((s) => (
              <StepItem key={s.key} s={s} />
            ))}
          </ol>
        </>
      ) : (
        <div className="pl-td-row">{body}</div>
      )}
    </li>
  );
}

/** The four roles, with the models session.started names (a non-real adapter kind is shown with it). */
function HowItWorks({ events }: { events: Ev[] }) {
  const head = useMemo(() => runHeader(events), [events]);
  const label = (role: string) => {
    const m = head?.models.find((x) => x.role === role);
    return m ? `${m.model_id}${m.kind === "real_http" ? "" : ` (${m.kind})`}` : null;
  };
  const voices = [...new Set([label("fast_user"), label("fast_cp")].filter((x) => x !== null))].join(" / ");
  const slow = label("slow");
  return (
    <Card className="pl-how">
      <details>
        <summary>How ProxyLoop works</summary>
        <ul>
          <li>
            <Icon name="planner" size="sm" />
            <span>
              <b>Planner</b> reads both conversations and decides the next step. {slow && <code>{slow}</code>}
            </span>
          </li>
          <li>
            <Icon name="voice" size="sm" />
            <span>
              <b>Chat voice and phone voice</b> do the talking, one on each lane. {voices && <code>{voices}</code>}
            </span>
          </li>
          <li>
            <Icon name="guard" size="sm" />
            <span>
              <b>Guard</b> checks every binding step: read-back, your limits, your approval.
            </span>
          </li>
          <li>
            <Icon name="you" size="sm" />
            <span>
              <b>You</b> approve or loosen limits, only by a click; in a simulated run the simulated approver stands in.
            </span>
          </li>
        </ul>
      </details>
    </Card>
  );
}
