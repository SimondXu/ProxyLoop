// The "Confirm your limits" card (redesign §3.2): Guard's mandate.proposed,
// confirmed only by a click on it, posted once through S1-SYS-41's route. The
// kernel's mandate.decided alone decides it (I6).
import { limitRows, limitsStatusText, type MandateStatus, type MandateView } from "../mandate";
import type { Decision } from "../liveApi";
import type { Ev } from "../replay";
import { aboutClock } from "../terms";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { Icon } from "../ui/Icon";
import "./cards.css";

const UNDECIDED: MandateStatus[] = ["open", "pending", "sent"];

type Props = { view: MandateView; events: Ev[]; decide: (v: MandateView, d: Decision) => void };

export function LimitsCard({ view, events, decide }: Props) {
  const { mandate: m, status, error } = view;
  const open = status === "open";
  const expiry = m.expires_ms == null ? null : aboutClock(events, m.expires_ms);
  const title = UNDECIDED.includes(status)
    ? "Confirm your limits"
    : status === "granted"
      ? "The agent can say yes inside these limits"
      : "Limits the planner proposed";
  return (
    <article className={`pl-gcard pl-limits ${status}`} aria-label={`Limits ${m.mandate_id}`}>
      <p className="pl-gcard-from">
        <Icon name="guard" size="xs" />
        Guard card · limits the planner proposed from your messages
      </p>
      <div className="pl-limits-kick">
        <span className="pl-label">Your limits</span>
        <Chip tone={open ? "you" : status === "granted" ? "ok" : "neutral"}>
          <span aria-label="Limits status">{limitsStatusText(view)}</span>
        </Chip>
      </div>
      <h3>{title}</h3>
      <dl className="pl-facts">
        {limitRows(m).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {expiry && <p className="meta">These limits are valid until {expiry}.</p>}
      <p className="pl-note">
        <Icon name="private" size="sm" />
        Kept private: the phone voice never sees these numbers, so it can't give them away.
      </p>
      {error && <p role="alert">{error}</p>}
      {UNDECIDED.includes(status) && (
        <div className="pl-gcard-actions">
          <Button variant="primary" disabled={!open} onClick={() => decide(view, "granted")}>
            Confirm limits
          </Button>
          <Button disabled={!open} onClick={() => decide(view, "denied")}>
            Not these
          </Button>
        </div>
      )}
      <details className="pl-gcard-tech">
        <summary>Technical details</summary>
        <p className="pl-mono">
          mandate {m.mandate_id} · hash {m.mandate_hash.slice(0, 12)}… · authority epoch {m.epoch}
        </p>
      </details>
    </article>
  );
}
