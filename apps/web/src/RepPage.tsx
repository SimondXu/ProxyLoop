// The human rep page (?rep=<case_id>, redesign §3.3): only what a counterparty can hear or has
// said (rep.ts), from the rep's own filtered stream (/ws/rep, never /ws/live).
// The rep enters through GET /rep/{case_id} (liveApi.ts), which sets its cookies.
// No AppShell: the operator's navigation and the principal's band are not the rep's.
// The rep speaks only while the kernel's call is open (S1-SYS-61).
import { useMemo, useState } from "react";
import { Composer, Connection } from "./Live";
import { unechoed, type Sent } from "./liveState";
import { postRep, type Failed } from "./liveApi";
import { callState, parseRepFrame, repLine, type RepLine } from "./rep";
import { Chip } from "./ui/Chip";
import { useEventStream } from "./useEventStream";
import "./rep.css";

const WHO: Record<RepLine["who"], string> = { agent: "Agent", rep: "You", call: "Call" };
// serve answers 409 {reason: "not_open"} to a rep line before the call opens; never retried.
const notOpen = (r: Failed) => (r.status === 409 && r.reason === "not_open" ? "The call hasn't started yet" : undefined);

export function RepPage({ caseId }: { caseId: string }) {
  const { stream, reconnect } = useEventStream("rep", caseId, parseRepFrame);
  const lines = useMemo(() => stream.events.map(repLine).filter((l) => l !== null), [stream.events]);
  const call = useMemo(() => callState(stream.events), [stream.events]);
  const [sent, setSent] = useState<Sent[]>([]);
  const send = async (text: string) => {
    const after = stream.next;
    const r = await postRep(caseId, text);
    if (r.ok) setSent((s) => [...s, { text, after }]);
    return r;
  };
  const pending = unechoed(sent, lines.filter((l) => l.who === "rep"));

  return (
    <main className="pl-main rep">
      <header className="bar">
        <h1>You're the rep on this call</h1>
        <Chip tone="sim">Human rep mode</Chip>
        <Connection stream={stream} reconnect={reconnect} />
      </header>
      <p role="note" className="pl-rep-about">
        The caller is an AI agent (ProxyLoop) acting for a customer. You're playing the company's rep. This page shows only
        what's said on the call.
      </p>
      <ol aria-label="Call transcript" className="transcript">
        {lines.map((l) => (
          <li key={l.seq} className={`rep-${l.who}`}>
            <strong>{WHO[l.who]}:</strong> {l.text}
          </li>
        ))}
      </ol>
      <Composer
        label="Say to the agent"
        post={send}
        pending={pending.map((s) => s.text)}
        closed={call === "open" ? undefined : call === "ended" ? "The call has ended" : "Waiting for the call to start"}
        explain={notOpen}
      />
      <details className="pl-rep-hint">
        <summary>How to state an offer</summary>
        <p>State offers with price, term, fees and plan changes; the agent will ask you to read them back.</p>
      </details>
    </main>
  );
}
