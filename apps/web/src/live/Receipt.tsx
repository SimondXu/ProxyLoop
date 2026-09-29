// The receipt (redesign §3.2, S1-SYS-51; v4 result card, S1-SYS-80): the chat's last item, at session.ended.
// Its variant and words are outcome.ts's; the terms are Guard's (terms.ts), the
// approver the kernel's grant of the card whose accept was released (decision.ts).
// The cost is session.ended's spend, formatted only: no totals, no savings (rule 13).
import { useMemo, useRef } from "react";
import { approvalCards, type Posting } from "../approval";
import { conversation } from "../conversation";
import { acceptedHeadline, acceptOf, approvedBy } from "../decision";
import { confirmations, receiptKind, receiptTitle, spendLines, unverifiedCommit, verifiedLine, type Outcome } from "../outcome";
import type { Ev } from "../replay";
import { latestOffers, READBACK_CHIP, termRows, type TermRow } from "../terms";
import { Chip } from "../ui/Chip";
import { Icon } from "../ui/Icon";
import "./cards.css";
import "./receipt.css";

const NO_POSTS = new Map<string, Posting>();
const TONE: Record<string, "err" | "ok" | "neutral"> = { verified: "ok", endpoint: "err", error: "err" };
/** The card's label before v4: the tag's words whenever the headline is the title (never the same words twice). */
const RECEIPT = "Receipt";

function Terms({ label, rows }: { label: string; rows: TermRow[] }) {
  return (
    <ul className="pl-terms" aria-label={label}>
      {rows.map((r) => (
        <li key={r.field}>
          <span className="pl-term-label">{r.label}</span> <span className="pl-term-value">{r.value}</span>{" "}
          <Chip tone={r.status === "confirmed" ? "ok" : "neutral"}>{READBACK_CHIP[r.status] ?? r.status}</Chip>
        </li>
      ))}
    </ul>
  );
}

/** Scroll to and focus the last call card's heading in this stream (ConversationView's CallCard). */
function backToCall(from: HTMLElement | null) {
  const heads = from?.closest(".pl-tx")?.querySelectorAll<HTMLElement>(".pl-call h3");
  const head = heads?.[heads.length - 1];
  if (!head) return;
  head.tabIndex = -1;
  head.scrollIntoView({ block: "start" });
  head.focus({ preventScroll: true });
}

export function Receipt({ events, outcome }: { events: Ev[]; outcome: Outcome }) {
  const ref = useRef<HTMLElement>(null);
  const kind = receiptKind(outcome);
  const tone = TONE[kind] ?? "neutral";
  const title = receiptTitle(kind, outcome);
  const note = unverifiedCommit(kind, events);
  // VERIFIED_COMPLETE: the granted card whose accept Guard released on the call.
  const approved = useMemo(
    () => approvalCards(events, NO_POSTS).findLast((v) => v.status === "granted" && acceptOf(events, v).state === "released"),
    [events],
  );
  // The stream shows a call card iff the conversation has call lines (stream.ts).
  const called = useMemo(() => conversation(events).call.length > 0, [events]);
  const verified = kind === "verified";
  const terms = verified && approved ? termRows(events, approved.card) : [];
  // Verified with the approved card's price: the headline is its terms and the title moves to the tag.
  const accepted = verified ? acceptedHeadline(terms) : null;
  const offers = kind === "info_only" || kind === "no_deal" ? latestOffers(events) : [];
  const ids = verified ? confirmations(events) : [];
  const verifier = verifiedLine(events);
  return (
    <section ref={ref} className={`pl-gcard pl-outcome pl-outcome-${tone}`} aria-label="Outcome">
      <Chip tone={tone === "ok" ? "ok" : "neutral"} className={`pl-outcome-tag pl-outcome-tag-${tone}`}>
        <Icon name={verified ? "guard" : "ended"} size="xs" />
        {accepted ? title : RECEIPT}
      </Chip>
      <h3 className="pl-outcome-head">{accepted ?? title}</h3>
      {note && <p className="pl-outcome-line pl-outcome-note">{note}</p>}
      {verified && (
        <>
          {verifier && <p className="meta pl-outcome-line">{verifier}</p>}
          {(approved || ids.length > 0) && (
            <div className="pl-outcome-panel">
              {approved && <Terms label="Accepted terms" rows={terms} />}
              {ids.map((id) => (
                <p key={id} className="pl-outcome-kv">
                  <span className="pl-term-label">Confirmation</span> <span className="pl-mono">{id}</span>
                </p>
              ))}
            </div>
          )}
          {approved && <p className="meta pl-outcome-line">{approvedBy(events, approved)}</p>}
        </>
      )}
      {offers.map((o) => (
        <div key={o.offer_ref} className="pl-outcome-panel">
          <Terms label={`Offer ${o.offer_ref}, revision ${o.revision}`} rows={termRows(events, o)} />
        </div>
      ))}
      {called && (
        <button type="button" className="pl-outcome-back" onClick={() => backToCall(ref.current)}>
          Back to the call
        </button>
      )}
      <details className="pl-gcard-tech pl-outcome-tech">
        <summary>Cost and details</summary>
        <ul className="pl-outcome-cost" aria-label="Cost">
          {spendLines(events).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
        <p className="pl-mono">
          Reason: {outcome.reason} · last case status: {outcome.status ?? "none"}
          {outcome.verdict ? ` · verifier: ${outcome.verdict}` : ""}
        </p>
      </details>
    </section>
  );
}
