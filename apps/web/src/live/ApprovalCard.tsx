// The approval card (redesign §3.2; v4's layout, S1-SYS-78), a Guard card in the chat column. Its
// state is approval.ts's; it moves only on fixed-emitter events, and only a click posts (one POST
// per click, no retry, no shortcut, no client-clock timer that changes state). "Your limit" sits
// beside "This offer" with no verdict and no difference: Guard alone judges the mandate (root ruling (a)).
import { useEffect, useMemo, useState } from "react";
import type { CardStatus, CardView } from "../approval";
import {
  acceptOf,
  approvalStatusText,
  headline,
  limitBar,
  limitTextRows,
  offerRows,
  PAUSED,
  PROGRESS,
  readbackCount,
  STOPPED,
  why,
  whyNote,
  type LimitBar,
} from "../decision";
import { holdElapsed, holdElapsedAt, mmss } from "../hold";
import type { Decision } from "../liveApi";
import type { MandateView } from "../mandate";
import { HUMAN_PRINCIPAL, honesty } from "../provenance";
import type { Ev } from "../replay";
import { aboutClock, READBACK_CHIP, termRows, whole } from "../terms";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { Icon } from "../ui/Icon";
import "../ui/Banner.css";
import "./cards.css";

// A raised fence does not block the approval (guard.decide does not check fences);
// it holds the accept (ARCHITECTURE §9.4), so the card says so while that matters.
const UNDECIDED: CardStatus[] = ["open", "pending", "sent"];
const CHIP_TONE: Record<string, "ok" | "neutral" | "over"> = { confirmed: "ok", heard: "neutral", unknown: "over" };

/** The hold line's clock: a live page ticks after the latest event; a replay passes its playback time `t` (t_ms). */
export type CardClock = { kind: "live" } | { kind: "replay"; t: number };

type Props = {
  view: CardView;
  events: Ev[];
  mandates: MandateView[];
  fenced: boolean;
  caseStatus: string | null;
  decide: (v: CardView, d: Decision) => void;
  clock: CardClock;
};

export function ApprovalCard({ view, events, mandates, fenced, caseStatus, decide, clock }: Props) {
  const { card, status, error } = view;
  const terms = useMemo(() => termRows(events, card), [events, card]);
  const rows = useMemo(() => offerRows(terms, mandates), [terms, mandates]);
  const bar = useMemo(() => limitBar(events, card, mandates), [events, card, mandates]);
  const textRows = limitTextRows(mandates);
  const accept = acceptOf(events, view);
  const open = status === "open";
  const price = rows.find((r) => r.field === "monthly_price")?.value;
  const limits = rows.some((r) => r.limit !== null); // with no granted mandate the "Your limit" column is omitted
  const held = status === "granted" && accept.state !== "released" && accept.state !== "revoked";
  const paused = fenced && (UNDECIDED.includes(status) || held);
  const progress = status === "granted" && caseStatus ? PROGRESS[caseStatus] : undefined;
  const expiry = aboutClock(events, card.expires_ms);
  const human = honesty(events).principal !== null;
  const holding = useHold(events, open, clock);
  const note = whyNote(mandates);
  return (
    <article className={`pl-gcard pl-decision ${status}`} aria-label={`Approval ${card.approval_id}`}>
      <p className="pl-gcard-from">
        <Icon name="guard" size="xs" />
        Guard card · your approval is needed
      </p>
      <div className="pl-decision-top">
        <div className="pl-decision-tags">
          <Chip tone={open ? "you" : status === "granted" ? "ok" : "neutral"}>
            <Icon name="you" size="xs" />
            <span aria-label="Approval status">{approvalStatusText(view, events)}</span>
          </Chip>
          {holding && (
            <p className="pl-hold">
              <Icon name="hold" size="xs" />
              <span>
                The rep is holding · <b>{holding}</b>
              </span>
            </p>
          )}
        </div>
        <h3>{headline(terms)}</h3>
        <p className="pl-decision-why">{why(mandates)}</p>
        {note && <p className="pl-decision-note">{note}</p>}
      </div>
      {bar && <PriceBar bar={bar} />}
      {rows.length > 0 ? (
        <div className={`pl-terms-panel${limits ? " pl-terms-limits" : ""}`}>
          <div className="pl-terms-head">
            <span className="pl-terms-count">
              <Icon name="guard" size="xs" />
              {readbackCount(rows)}
            </span>
            <span aria-hidden="true">This offer</span>
            {limits && <span aria-hidden="true">Your limit</span>}
          </div>
          <ul className="pl-terms" aria-label="Read-back progress">
            {rows.map((r) => (
              <li key={r.field}>
                <span className="pl-term-label">{r.label}</span> <span className="pl-term-value">{r.value}</span>{" "}
                {r.limit !== null && (
                  <>
                    <span className="pl-term-limit">
                      <span className="pl-term-limit-l">Your limit: </span>
                      {r.limit}
                    </span>{" "}
                  </>
                )}
                <Chip tone={CHIP_TONE[r.status] ?? "neutral"}>
                  {r.status === "confirmed" && <Icon name="guard" size="xs" />}
                  <span className="pl-chip-text">{READBACK_CHIP[r.status] ?? r.status}</span>
                </Chip>
              </li>
            ))}
          </ul>
          {textRows.length > 0 && (
            <dl className="pl-terms-text">
              {textRows.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>
                    <span className="pl-term-limit-l">Your limit: </span>
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ) : (
        <p className="meta">Guard has not read this offer back yet.</p>
      )}
      <p className="pl-decision-conseq">
        Approving lets the agent say yes to <b>exactly these terms</b> on the call. If anything changes, or you send a message
        first, it asks you again.
      </p>
      {expiry && <p className="meta">This card is valid until {expiry}; it changes only when Guard says so.</p>}
      {paused && (
        <p className="pl-banner pl-banner-over" aria-label="Fence note">
          {PAUSED}
        </p>
      )}
      {accept.state === "revoked" && accept.reason === "fence" && (
        <p className="pl-banner pl-banner-err" role="note">
          {STOPPED}
        </p>
      )}
      {progress && <p className="pl-decision-progress">{progress}</p>}
      {error && <p role="alert">{error}</p>}
      <div className="pl-gcard-actions">
        {/* Never on a simulated principal's card: the simulated approver decides there (I6, honesty().principal). */}
        {human && (
          <p className="pl-sign-only">
            <Icon name="private" size="sm" />
            {HUMAN_PRINCIPAL}
          </p>
        )}
        <Button variant="primary" disabled={!open} onClick={() => decide(view, "granted")}>
          {price ? `Approve ${whole(price)}/mo` : "Approve"}
        </Button>
        <Button disabled={!open} onClick={() => decide(view, "denied")}>
          Decline
        </Button>
      </div>
      <details className="pl-gcard-tech">
        <summary>Guard's read-back record and technical details</summary>
        <div className="pl-quote" aria-label="Readback">
          {card.readback_text}
        </div>
        <p className="pl-mono">
          approval {card.approval_id} · offer {card.offer_ref} rev {card.revision} · terms {card.terms_hash.slice(0, 12)}… ·
          authority epoch {card.authority_epoch}
        </p>
      </details>
    </article>
  );
}

/** Your limit and this offer on one neutral track, each amount printed by its mark; the graphic itself is aria-hidden. */
function PriceBar({ bar }: { bar: LimitBar }) {
  // A label's own anchor moves with its mark, so it never leaves the track at either end.
  const label = (at: number) => ({ left: `${at}%`, transform: `translateX(-${at}%)` });
  return (
    <div className="pl-lbar">
      <p className="pl-lbar-l" style={label(bar.limitAt)}>
        Your limit <b>{bar.limit}</b>
      </p>
      <div className="pl-lbar-t" aria-hidden="true">
        <span className="pl-lbar-lim" style={{ left: `${bar.limitAt}%` }} />
        <span className="pl-lbar-dot" style={{ left: `${bar.offerAt}%` }} />
      </div>
      <p className="pl-lbar-l" style={label(bar.offerAt)}>
        This offer <b>{bar.offer}</b>
      </p>
    </div>
  );
}

/**
 * The hold line's "m:ss" while the card is open and the rep holds, else null; display only.
 * A replay follows its playback clock (recorded t_ms). A live page ticks once a second: the
 * latest event's t_ms plus the local time since it arrived. Nothing acts on it.
 */
function useHold(events: Ev[], open: boolean, clock: CardClock): string | null {
  const live = clock.kind === "live";
  const latest = `${events.length}:${events.at(-1)?.event_id ?? ""}`;
  const on = open && live && holdElapsed(events) !== null;
  const [tick, setTick] = useState({ latest, ms: 0 });
  useEffect(() => {
    if (!on) return;
    const arrived = performance.now();
    const id = setInterval(() => setTick({ latest, ms: performance.now() - arrived }), 1000);
    return () => clearInterval(id);
  }, [latest, on]);
  if (!open) return null;
  const elapsed = clock.kind === "replay" ? holdElapsedAt(events, clock.t) : holdElapsed(events, on && tick.latest === latest ? tick.ms : 0);
  return elapsed === null ? null : mmss(elapsed);
}
