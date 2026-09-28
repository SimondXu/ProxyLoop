// The principal's "Your role" card (S1-SYS-65, role.ts): on the start page for the chosen task, and
// folded on the principal's live page for the case's own task. The rep page never asks for it.
import { useEffect, useState } from "react";
import { getCaseCard, getTaskCard } from "./liveApi";
import { approvalRows, factLabel, factRows, parseRoleCard, stopWhen, type RoleCard } from "./role";
import "./live/cards.css"; // .pl-label, .pl-facts
import "./YourRole.css";

/** The card of a task ("task": the operator's) or of a case ("case": its user's); null while it loads. */
export function useRoleCard(of: "task" | "case", id: string): RoleCard | string | null {
  const [got, setGot] = useState<{ id: string; card: RoleCard | string } | null>(null);
  useEffect(() => {
    if (!id) return;
    let live = true;
    void (of === "task" ? getTaskCard(id) : getCaseCard(id)).then((r) => {
      if (live) setGot({ id, card: r.ok ? parseRoleCard(r.body) : r.error });
    });
    return () => {
      live = false;
    };
  }, [of, id]);
  return got?.id === id ? got.card : null;
}

function Rows({ title, rows }: { title: string; rows: [string, string][] }) {
  if (rows.length === 0) return null;
  return (
    <>
      <h3 className="pl-label">{title}</h3>
      <dl className="pl-facts">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}

/** The card's sections; `card` a string is why it is unavailable (shown, never hidden). */
export function YourRole({ card }: { card: RoleCard | string | null }) {
  if (card === null) return <p className="meta">Loading your role…</p>;
  if (typeof card === "string") return <p className="meta">Your role is unavailable: {card}</p>;
  const facts = factRows(card.facts);
  return (
    <div className="pl-role-body">
      <h3 className="pl-label">Who you are</h3>
      <p>{card.persona}</p>
      <p className="meta">Your provider: {card.company}</p>
      <h3 className="pl-label">Your goal</h3>
      <p>{card.goal}</p>
      <Rows title="Give these when asked" rows={facts.identity} />
      <Rows title="Other facts you may share" rows={facts.shareable} />
      <Rows title="Facts you keep to yourself" rows={facts.private} />
      {card.approval === null ? (
        <>
          <h3 className="pl-label">What you would approve</h3>
          <p>Nothing: this task only gathers information, and nothing is accepted.</p>
        </>
      ) : (
        <>
          <Rows title="What you would approve" rows={approvalRows(card.approval)} />
          <p className="meta">
            If the assistant asks you to approve a deal, approve it only within these, and decline anything outside them. This is not a target
            to aim for.
          </p>
        </>
      )}
      {card.stop && (
        <>
          <h3 className="pl-label">When to stop</h3>
          <p>
            {stopWhen(card.stop.trigger)}: {card.stop.text_hint}
          </p>
          <Rows title="Your changed facts" rows={Object.entries(card.stop.change ?? {}).map(([k, v]) => [factLabel(k), v])} />
        </>
      )}
    </div>
  );
}
