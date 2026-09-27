// The human rep page (?rep=<case_id>): only what a counterparty can hear or has
// said (rep.ts), from the rep's own filtered stream (/ws/rep, never /ws/live).
import { useMemo, useState } from "react";
import { Composer, Connection } from "./Live";
import { unechoed, type Sent } from "./liveState";
import { postRep } from "./liveApi";
import { repLine, type RepLine } from "./rep";
import { useEventStream } from "./useEventStream";

const WHO: Record<RepLine["who"], string> = { agent: "Agent", rep: "You", call: "Call" };

export function RepPage({ caseId }: { caseId: string }) {
  const { stream, reconnect } = useEventStream("rep", caseId);
  const lines = useMemo(() => stream.events.map(repLine).filter((l) => l !== null), [stream.events]);
  const [sent, setSent] = useState<Sent[]>([]);
  const send = async (text: string) => {
    const after = stream.next;
    const r = await postRep(caseId, text);
    if (r.ok) setSent((s) => [...s, { text, after }]);
    return r;
  };
  const pending = unechoed(sent, lines.filter((l) => l.who === "rep"));

  return (
    <main className="rep">
      <header className="bar">
        <h1>Rep call</h1>
        <Connection stream={stream} reconnect={reconnect} />
      </header>
      <p role="note" className="note">
        human rep mode: not for live sessions until the server-side filter lands (S1-SYS-10)
      </p>
      <ol aria-label="Call transcript" className="transcript">
        {lines.map((l) => (
          <li key={l.seq} className={`rep-${l.who}`}>
            <strong>{WHO[l.who]}:</strong> {l.text}
          </li>
        ))}
      </ol>
      <Composer label="Say to the agent" post={send} pending={pending.map((s) => s.text)} />
    </main>
  );
}
