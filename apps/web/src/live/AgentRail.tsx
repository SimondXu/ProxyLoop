// The live page's rail (redesign §3.2 AgentRail): the status line with the
// planner's pulse, the limits in force, the steps (timeline.ts) and how the
// roles work. Its payload reads all go through helpers: timeline.ts (steps,
// status line, planner), mandate.ts's limitRows and limitsStatusText (the
// limits) and replay.ts's runHeader (the models).
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CardView } from "../approval";
import * as C from "../copy";
import { limitRows, limitsStatusText, type MandateView } from "../mandate";
import { runHeader, type Ev } from "../replay";
import { groups, now, planner, timeline, type Step, type StepIcon } from "../timeline";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Icon, type ICONS } from "../ui/Icon";
import "./rail.css";

type Props = { events: Ev[]; cards: CardView[]; mandates: MandateView[] };

export function AgentRail({ events, cards, mandates }: Props) {
  const steps = useMemo(() => timeline(events), [events]);
  const line = useMemo(() => now(events, steps, cards, mandates), [events, steps, cards, mandates]);
  const pulse = useMemo(() => planner(events), [events]);
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
      <Steps steps={steps} />
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

const AT_END_PX = 8;

/** The steps in their groups; earlier groups folded. Follows the newest step while scrolled to the end. */
function Steps({ steps }: { steps: Step[] }) {
  const box = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    const el = box.current;
    if (following && el) el.scrollTop = el.scrollHeight;
  }, [following, steps.length]);
  const onScroll = () => {
    const el = box.current;
    if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= AT_END_PX);
  };
  const all = groups(steps);
  return (
    <Card className="pl-steps" aria-label="Steps">
      <h2 className="pl-rail-h">
        What the agent did <span className="meta">time since start</span>
      </h2>
      {/* focusable: a keyboard can scroll it (axe scrollable-region-focusable) */}
      <div className="pl-steps-scroll" ref={box} onScroll={onScroll} tabIndex={0} role="group" aria-label="Steps list">
        {all.length === 0 && <p className="meta">No steps yet.</p>}
        {all.map((g, i) =>
          i < all.length - 1 ? (
            <details key={`${g.name}:${i}`} className="pl-grp">
              <summary>
                {g.name} <span className="pl-grp-done">✓ {g.steps.length} steps done</span>
              </summary>
              <ol className="pl-st-list">{g.steps.map((s) => <StepItem key={s.key} s={s} />)}</ol>
            </details>
          ) : (
            <section key={`${g.name}:${i}`} aria-label={g.name}>
              <h3 className="pl-grp-name">{g.name}</h3>
              <ol className="pl-st-list">{g.steps.map((s) => <StepItem key={s.key} s={s} />)}</ol>
            </section>
          ),
        )}
      </div>
    </Card>
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
