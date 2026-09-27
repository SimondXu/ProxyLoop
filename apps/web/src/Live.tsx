// The live shell (?live=<run_id>), fed by /ws/live: by default the conversation
// view (Conversation.tsx) with the chat input in the chat pane; with
// ?view=engineer the replay's lanes, cards and drawer. Both keep the honesty band,
// the status line and the authority strip in the sticky header; the limits and
// approval cards sit in the chat column, above the input. It shows only
// what events say. Models are chosen on the start page (?start); here RunSummary
// shows the ones session.started names.
import { useId, useMemo, useRef, useState, type FormEvent } from "react";
import { Drawer, Lanes, RunSummary, useDrill } from "./App";
import { parties } from "./conversation";
import { Panes, StatusBar, useView } from "./ConversationView";
import { approvalCards, type CardView, type Posting } from "./approval";
import { authorityStrip, type Strip } from "./authority";
import { parseEvent, unechoed, type Framed, type Sent, type Stream } from "./liveState";
import { ApprovalCard } from "./live/ApprovalCard";
import { LimitsCard } from "./live/LimitsCard";
import { postApproval, postMandate, postMessage, type Decision, type PostResult } from "./liveApi";
import { mandateCards, type MandateView } from "./mandate";
import { honesty } from "./provenance";
import { indexEvents } from "./replay";
import { AppShell } from "./shell/AppShell";
import { HonestyBand } from "./shell/HonestyBand";
import { Button } from "./ui/Button";
import { useEventStream } from "./useEventStream";

const CHAT_LABEL = "Message to the assistant";
// serve reads prompts.jsonl, which the kernel writes when it closes the run (kernel/session.py).
const PROMPTS_LATER = "Prompts come from prompts.jsonl, which the kernel writes as the run closes (after session.ended).";

export function Live({ runId }: { runId: string }) {
  const { stream, reconnect } = useEventStream("live", runId, parseEvent);
  const events = stream.events;
  const index = useMemo(() => indexEvents(events), [events]);
  const ended = events.some((e) => e.type === "session.ended");
  const { drill, open, close } = useDrill(runId, ended ? undefined : PROMPTS_LATER);
  const [god, setGod] = useState(false);
  const [posts, setPosts] = useState<ReadonlyMap<string, Posting>>(new Map());
  const [mandatePosts, setMandatePosts] = useState<ReadonlyMap<string, Posting>>(new Map());
  const [sent, setSent] = useState<Sent[]>([]);

  const cards = useMemo(() => approvalCards(events, posts), [events, posts]);
  const mandates = useMemo(() => mandateCards(events, mandatePosts), [events, mandatePosts]);
  const strip = useMemo(() => authorityStrip(events), [events]);
  const who = useMemo(() => parties(events), [events]); // live: only what has arrived
  const h = useMemo(() => honesty(events), [events]);
  // Cards with a pending or ok post: a second click, even before a re-render, never POSTs again.
  const claimed = useRef(new Set<string>());
  const once = (key: string, set: typeof setPosts, id: string, send: () => Promise<PostResult>) => {
    if (claimed.current.has(key)) return;
    claimed.current.add(key);
    set((m) => new Map(m).set(id, "pending"));
    void send().then((r) => {
      if (!r.ok) claimed.current.delete(key); // a failed post may be clicked again, by hand
      set((m) => new Map(m).set(id, r));
    });
  };
  const decide = (view: CardView, decision: Decision) => {
    const id = view.card.approval_id;
    once(`approval:${id}`, setPosts, id, () => postApproval(runId, view.card, decision));
  };
  const decideMandate = (view: MandateView, decision: Decision) => {
    const id = view.mandate.mandate_id;
    once(`mandate:${id}`, setMandatePosts, id, () => postMandate(runId, view.mandate, decision));
  };
  const send = async (text: string) => {
    const after = stream.next;
    const r = await postMessage(runId, text);
    if (r.ok) setSent((s) => [...s, { text, after }]);
    return r;
  };
  const echoes = events.filter((e) => e.type === "user.msg").map((e) => ({ seq: e.seq, text: String(e.payload.text) }));
  const { engineer, link } = useView();
  // Guard cards in event order, in the chat column above the input.
  const guardCards = [
    ...mandates.map((v) => ({ seq: v.seq, el: <LimitsCard key={`m:${v.mandate.mandate_id}`} view={v} events={events} decide={decideMandate} /> })),
    ...cards.map((v) => ({
      seq: v.seq,
      el: (
        <ApprovalCard
          key={`a:${v.card.approval_id}`}
          view={v}
          events={events}
          mandates={mandates}
          fenced={strip.fences.length > 0}
          caseStatus={strip.status}
          decide={decide}
        />
      ),
    })),
  ].sort((a, b) => a.seq - b.seq);
  const composer = (
    <>
      {guardCards.length > 0 && <div className="pl-gcards">{guardCards.map((c) => c.el)}</div>}
      <Composer label={CHAT_LABEL} post={send} pending={unechoed(sent, echoes).map((s) => s.text)} />
    </>
  );

  return (
    <AppShell>
      <div className="pl-sticky">
        <HonestyBand h={h} />
        <header className="bar">
          <h1>ProxyLoop live · {runId}</h1>
          <Connection stream={stream} reconnect={reconnect} count />
          {link}
          {engineer && (
            <label>
              <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
            </label>
          )}
        </header>
        <StatusBar events={events} />
        <details className="authority">
          <summary>Authority details (raw case status, fence, epoch)</summary>
          <AuthorityStrip a={strip} />
        </details>
      </div>
      <RunSummary events={events} />
      {engineer ? (
        <>
          <p className="meta">{ended ? "Run ended: the prompt drill-down reads prompts.jsonl." : PROMPTS_LATER}</p>
          {composer}
          <Lanes shown={events} index={index} god={god} open={open} />
          {drill && <Drawer drill={drill} close={close} />}
        </>
      ) : (
        <Panes events={events} p={who} announce composer={composer} />
      )}
    </AppShell>
  );
}

/** The stream's phase and close reason; `count` is left out where raw events are not the viewer's business. */
export function Connection<T extends Framed>({
  stream,
  reconnect,
  count,
}: {
  stream: Stream<T>;
  reconnect: () => void;
  count?: boolean;
}) {
  return (
    <>
      <output aria-label="Connection">
        {stream.phase}
        {stream.message && stream.phase !== "error" ? `: ${stream.message}` : ""}
        {count ? ` · ${stream.events.length} events` : ""}
      </output>
      {stream.phase === "closed" && (
        <button type="button" onClick={reconnect}>
          Reconnect from seq {stream.next}
        </button>
      )}
      {stream.phase === "error" && <p role="alert">Stream stopped: {stream.message}</p>}
    </>
  );
}

function AuthorityStrip({ a }: { a: Strip }) {
  const fence = a.fences.length > 0 ? `raised (${a.fences.join(", ")})` : a.lastFence ? `cleared (${a.lastFence.fence_id})` : "none";
  return (
    <section className="bar strip" aria-label="Authority">
      <span aria-label="Case status">status {a.status ?? "no status.changed yet"}</span>
      <span aria-label="Fence">fence {fence}</span>
      <span aria-label="Epoch">epoch {a.epoch}</span>
      <span aria-label="Last revoked">
        last speak.revoked {a.revoked ? `${a.revoked.reason} (${a.revoked.actor})` : "none"}
      </span>
      <span aria-label="Last denied">
        last action.denied {a.denied ? `${a.denied.intent}: ${a.denied.reason} (${a.denied.actor})` : "none"}
      </span>
    </section>
  );
}

/** A text input that posts once per submit; a sent text stays "pending" until its event arrives. */
export function Composer({
  label,
  post,
  pending,
}: {
  label: string;
  post: (text: string) => Promise<PostResult>;
  pending: string[];
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    setError("");
    void post(t).then((r) => {
      setBusy(false);
      if (r.ok) setText("");
      else setError(`${r.status ? `${r.status} ` : ""}${r.error}`);
    });
  };
  const id = useId();
  return (
    <form className="bar composer" aria-label={label} onSubmit={submit}>
      <label htmlFor={id}>{label}</label>
      <input id={id} value={text} onChange={(e) => setText(e.target.value)} />
      <Button variant="primary" type="submit" disabled={busy}>
        Send
      </Button>
      {error && <p role="alert">Not delivered: {error}</p>}
      {pending.length > 0 && (
        <ul aria-label="Pending" className="meta">
          {pending.map((p, i) => (
            <li key={i}>pending: {p} (appears when its event arrives)</li>
          ))}
        </ul>
      )}
    </form>
  );
}
