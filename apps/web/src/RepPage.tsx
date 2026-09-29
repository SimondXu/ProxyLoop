// The human rep page (?rep=<case_id>, redesign §3.3): only what a counterparty can hear or has
// said (rep.ts), from the rep's own filtered stream (/ws/rep, never /ws/live).
// The rep enters through GET /rep/{case_id} (liveApi.ts), which sets its cookies.
// No AppShell: the operator's navigation and the principal's band are not the rep's.
// The rep speaks only while the kernel's call is open (S1-SYS-61). The transcript is a v4 call
// card (S1-SYS-92, as Live's): two voices, each under its name, "The agent" and "You".
import { useMemo, useState } from "react";
import { Composer, Connection, StreamAlert } from "./Live";
import { unechoed, type Sent } from "./liveState";
import { postRep, type Failed } from "./liveApi";
import { callState, parseRepFrame, repLine, type RepLine } from "./rep";
import { Chip } from "./ui/Chip";
import { Icon } from "./ui/Icon";
import { useEventStream } from "./useEventStream";
import "./live/live.css"; // the call card's look (.pl-call, .pl-line)
import "./rep.css";

const WHO: Record<RepLine["who"], string> = { agent: "The agent", rep: "You", call: "Call" };
const CALL: Record<ReturnType<typeof callState>, string> = { none: "Not started", open: "Connected", ended: "Call ended" };
// serve answers 409 {error: "not_open"} to a rep line before the call opens (serve/cases.py); never retried.
const notOpen = (r: Failed) => (r.status === 409 && r.error === "not_open" ? "The call hasn't started yet" : undefined);

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
        <StreamAlert stream={stream} reconnect={reconnect} />
      </header>
      <p role="note" className="pl-rep-about">
        The caller is an AI agent (ProxyLoop) acting for a customer. You're playing the company's rep. This page shows only
        what's said on the call.
      </p>
      <div className="pl-call" role="group" aria-labelledby="pl-rep-call">
        <div className="pl-call-h">
          <span className="pl-call-ic">
            <Icon name="call" size="sm" />
          </span>
          <div className="pl-call-tt">
            <h2 id="pl-rep-call">Call with the agent</h2>
            <p className="meta pl-rep-key">The agent: the AI caller · You: the company's rep</p>
          </div>
          <Chip>{CALL[call]}</Chip>
        </div>
        <ol aria-label="Call transcript" className="pl-call-lines">
          {lines.map((l) =>
            l.who === "call" ? (
              <li key={l.seq} className="pl-line pl-line-call">
                <span className="pl-sr">{WHO.call}: </span>
                {l.text}
              </li>
            ) : (
              <li key={l.seq} className={`pl-line pl-line-${l.who}`}>
                <div className="pl-line-body">
                  <span className="pl-who">{WHO[l.who]}</span>
                  <span className="pl-sr">: </span>
                  <p className="pl-bubble">{l.text}</p>
                </div>
              </li>
            ),
          )}
        </ol>
      </div>
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
      <details className="pl-rep-hint">
        <summary>Connection</summary>
        <p>
          <Connection stream={stream} />
        </p>
      </details>
    </main>
  );
}
