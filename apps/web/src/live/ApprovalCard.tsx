// The approval card (redesign §3.2), a Guard card in the chat column. Its state
// is approval.ts's; it moves only on fixed-emitter events, and only a click
// posts (one POST per click, no retry, no shortcut, no client-clock timer).
import { useMemo } from "react";
import type { CardStatus, CardView } from "../approval";
import { acceptOf, approvalStatusText, headline, PAUSED, priceLimit, PROGRESS, STOPPED, why } from "../decision";
import type { Decision } from "../liveApi";
import type { MandateView } from "../mandate";
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
const CHIP_TONE: Record<string, "guard" | "neutral" | "attn"> = { confirmed: "guard", heard: "neutral", unknown: "attn" };

type Props = {
  view: CardView;
  events: Ev[];
  mandates: MandateView[];
  fenced: boolean;
  caseStatus: string | null;
  decide: (v: CardView, d: Decision) => void;
};

export function ApprovalCard({ view, events, mandates, fenced, caseStatus, decide }: Props) {
  const { card, status, error } = view;
  const rows = useMemo(() => termRows(events, card), [events, card]);
  const accept = acceptOf(events, view);
  const open = status === "open";
  const price = rows.find((r) => r.field === "monthly_price")?.value;
  const limit = priceLimit(mandates);
  const held = status === "granted" && accept.state !== "released" && accept.state !== "revoked";
  const paused = fenced && (UNDECIDED.includes(status) || held);
  const progress = status === "granted" && caseStatus ? PROGRESS[caseStatus] : undefined;
  const expiry = aboutClock(events, card.expires_ms);
  return (
    <article className={`pl-gcard pl-decision ${status}`} aria-label={`Approval ${card.approval_id}`}>
      <p className="pl-gcard-from">
        <Icon name="guard" size="xs" />
        Guard card · your approval is needed
      </p>
      <div className="pl-decision-top">
        <Chip tone={open ? "attn" : status === "granted" ? "agent" : "neutral"}>
          <Icon name="you" size="xs" />
          <span aria-label="Approval status">{approvalStatusText(view, events)}</span>
        </Chip>
        <h3>{headline(rows)}</h3>
        <p className="pl-decision-why">{why(mandates)}</p>
      </div>
      {rows.length > 0 ? (
        <ul className="pl-terms" aria-label="Read-back progress">
          {rows.map((r) => (
            <li key={r.field}>
              <span className="pl-term-label">
                {r.label}
                {r.field === "monthly_price" && limit && <span className="pl-term-limit"> {limit}</span>}
              </span>
              <span className="pl-term-value">{r.value}</span>
              <Chip tone={CHIP_TONE[r.status] ?? "neutral"}>
                {r.status === "confirmed" && <Icon name="guard" size="xs" />}
                {READBACK_CHIP[r.status] ?? r.status}
              </Chip>
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">Guard has not read this offer back yet.</p>
      )}
      <p className="pl-decision-conseq">
        Approving lets the agent say yes to <b>exactly these terms</b> on the call. If anything changes, or you send a message
        first, it asks you again.
      </p>
      {expiry && <p className="meta">This card is valid until {expiry}; it changes only when Guard says so.</p>}
      {paused && (
        <p className="pl-banner pl-banner-attn" aria-label="Fence note">
          {PAUSED}
        </p>
      )}
      {accept.state === "revoked" && accept.reason === "fence" && (
        <p className="pl-banner pl-banner-danger" role="note">
          {STOPPED}
        </p>
      )}
      {progress && <p className="pl-decision-progress">{progress}</p>}
      {error && <p role="alert">{error}</p>}
      <div className="pl-gcard-actions">
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
