// The receipt (redesign §3.2, S1-SYS-51): the chat's last item, at session.ended.
// Its variant and words are outcome.ts's; the terms are Guard's (terms.ts), the
// approver the kernel's grant of the card whose accept was released (decision.ts).
// The cost is session.ended's spend, formatted only: no totals, no savings (rule 13).
import { useMemo } from "react";
import { approvalCards, type Posting } from "../approval";
import { acceptOf, approvedBy } from "../decision";
import { confirmations, receiptKind, receiptTitle, spendLines, unverifiedCommit, verifiedLine, type Outcome } from "../outcome";
import type { Ev } from "../replay";
import { latestOffers, READBACK_CHIP, termRows, type TermRow } from "../terms";
import { Chip } from "../ui/Chip";
import { Icon } from "../ui/Icon";
import "./cards.css";
import "./receipt.css";

const NO_POSTS = new Map<string, Posting>();
const TONE: Record<string, "danger" | "guard" | "neutral"> = { verified: "guard", endpoint: "danger", error: "danger" };

function Terms({ label, rows }: { label: string; rows: TermRow[] }) {
  return (
    <ul className="pl-terms" aria-label={label}>
      {rows.map((r) => (
        <li key={r.field}>
          <span className="pl-term-label">{r.label}</span> <span className="pl-term-value">{r.value}</span>{" "}
          <Chip tone={r.status === "confirmed" ? "guard" : "neutral"}>{READBACK_CHIP[r.status] ?? r.status}</Chip>
        </li>
      ))}
    </ul>
  );
}

export function Receipt({ events, outcome }: { events: Ev[]; outcome: Outcome }) {
  const kind = receiptKind(outcome);
  const note = unverifiedCommit(kind, events);
  // VERIFIED_COMPLETE: the granted card whose accept Guard released on the call.
  const approved = useMemo(
    () => approvalCards(events, NO_POSTS).findLast((v) => v.status === "granted" && acceptOf(events, v).state === "released"),
    [events],
  );
  const offers = kind === "info_only" || kind === "no_deal" ? latestOffers(events) : [];
  const ids = kind === "verified" ? confirmations(events) : [];
  const verifier = verifiedLine(events);
  return (
    <section className={`pl-gcard pl-outcome pl-outcome-${TONE[kind] ?? "neutral"}`} aria-label="Outcome">
      <p className="pl-gcard-from">
        <Icon name="guard" size="xs" />
        Receipt
      </p>
      <h3>{receiptTitle(kind, outcome)}</h3>
      {note && <p className="pl-outcome-line">{note}</p>}
      {kind === "verified" && (
        <>
          {approved && <Terms label="Accepted terms" rows={termRows(events, approved.card)} />}
          {ids.map((id) => (
            <p key={id} className="pl-outcome-line">
              Confirmation <span className="pl-mono">{id}</span>
            </p>
          ))}
          {verifier && <p className="pl-outcome-line">{verifier}</p>}
          {approved && <p className="pl-outcome-line">{approvedBy(events, approved)}</p>}
        </>
      )}
      {offers.map((o) => (
        <Terms key={o.offer_ref} label={`Offer ${o.offer_ref}, revision ${o.revision}`} rows={termRows(events, o)} />
      ))}
      <details className="pl-gcard-tech">
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
