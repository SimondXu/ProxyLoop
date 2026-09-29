// The live shell (?live=<run_id>), fed by /ws/live. The sticky header keeps the
// honesty band. By default the v4 case (ConversationView.tsx, S1-SYS-77): the case
// header (the title, the one tag; Reconnect if the stream drops); one stream (the chat, the cards and the
// call as call cards) above the message box; the Task details rail (AgentRail: the
// status line, limits, the to-do; your role; the authority details and the models, folded). With ?view=engineer, the replay's
// lanes, cards and drawer. It shows only what events say. Models are chosen on
// the start page (?start); here RunSummary shows the ones session.started names.
import { useId, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Drawer, Lanes, RunSummary, useDrill } from "./App";
import { parties } from "./conversation";
import { Panes, StatusBar, TechDetails, useView } from "./ConversationView";
import { approvalCards, type CardView, type Posting } from "./approval";
import { authorityStrip, type Strip } from "./authority";
import { parseEvent, unechoed, type Framed, type Sent, type Stream } from "./liveState";
import { ApprovalCard } from "./live/ApprovalCard";
import { AgentRail, NowCard } from "./live/AgentRail";
import { LimitsCard } from "./live/LimitsCard";
import { Sheet } from "./live/Sheet";
import { postApproval, postMandate, postMessage, type Decision, type Failed, type PostResult } from "./liveApi";
import { mandateCards, type MandateView } from "./mandate";
import { honesty } from "./provenance";
import { indexEvents } from "./replay";
import { AppShell } from "./shell/AppShell";
import { HonestyBand } from "./shell/HonestyBand";
import { taskName } from "./start";
import { termRows, whole } from "./terms";
import { Icon } from "./ui/Icon";
import { useEventStream } from "./useEventStream";
import { useRoleCard, YourRole } from "./YourRole";

const CHAT_LABEL = "Message to the assistant";
const CHAT_HINT = "Changed your mind? Say so. Any message pauses commitments until the agent reads it.";
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
  const role = useRoleCard("case", runId); // case_id = run_id (S1); only this page, never the rep's
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
  // Guard cards in event order: among the chat's lines, or above the input in the engineer view.
  const guardCards = [
    ...mandates.map((v) => ({ seq: v.seq, status: v.status, el: <LimitsCard key={`m:${v.mandate.mandate_id}`} view={v} events={events} decide={decideMandate} /> })),
    ...cards.map((v) => {
      const card = (
        <ApprovalCard
          key={`a:${v.card.approval_id}`}
          view={v}
          events={events}
          mandates={mandates}
          fenced={strip.fences.length > 0}
          caseStatus={strip.status}
          decide={decide}
          clock={{ kind: "live" }}
        />
      );
      if (v.status !== "open") return { seq: v.seq, status: v.status, el: card };
      const price = termRows(events, v.card).find((r) => r.field === "monthly_price")?.value;
      const bar = `Decision needed${price ? ` · ${whole(price)}/mo` : ""} · Review`;
      return { seq: v.seq, status: v.status, el: <Sheet key={`a:${v.card.approval_id}`} bar={bar} human={h.principal !== null}>{card}</Sheet> };
    }),
  ].sort((a, b) => a.seq - b.seq);
  const pending = unechoed(sent, echoes).map((s) => s.text);
  const start = events.find((e) => e.type === "session.started" && e.actor === "kernel");
  const authority = (
    <details className="authority">
      <summary>Authority details (raw case status, fence, epoch)</summary>
      <AuthorityStrip a={strip} />
    </details>
  );
  const details = (
    <>
      <StatusBar events={events} />
      {authority}
      <RunSummary events={events} />
    </>
  );
  const name = <h1>{start ? taskName(String(start.payload.task_ref)) : "Live case"}</h1>;
  const alert = <StreamAlert stream={stream} reconnect={reconnect} />;
  // The run id, the raw connection state and the event count: the engineer header, or the rail's Technical details.
  const run = (
    <>
      <span className="meta pl-runid">{runId}</span> <Connection stream={stream} count />
    </>
  );

  return (
    <AppShell>
      {engineer ? (
        <>
          <div className="pl-sticky">
            <HonestyBand h={h} />
            <header className="bar">
              {name}
              {run}
              {alert}
              {link}
              <label>
                <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
              </label>
            </header>
          </div>
          {details}
          <p className="meta">{ended ? "Run ended: the prompt drill-down reads prompts.jsonl." : PROMPTS_LATER}</p>
          {guardCards.length > 0 && <div className="pl-gcards">{guardCards.map((c) => c.el)}</div>}
          <Composer label={CHAT_LABEL} post={send} pending={pending} hint={CHAT_HINT} />
          <Lanes shown={events} index={index} god={god} open={open} />
          {drill && <Drawer drill={drill} close={close} />}
        </>
      ) : (
        <div className="pl-live">
          <div className="pl-sticky">
            <HonestyBand h={h} />
          </div>
          <Panes
            events={events}
            p={who}
            announce
            head={
              <>
                {name}
                {alert}
              </>
            }
            input={{ cards: guardCards, pending, composer: <Composer label={CHAT_LABEL} post={send} hint={CHAT_HINT} /> }}
            now={<NowCard events={events} cards={cards} mandates={mandates} />}
            details={
              <>
                <AgentRail events={events} mandates={mandates} />
                <details className="pl-card pl-role">
                  <summary>Your role</summary>
                  <YourRole card={role} />
                </details>
                <TechDetails>
                  <p className="meta pl-tech-run">{run}</p>
                  {authority}
                  <RunSummary events={events} />
                </TechDetails>
                {link}
              </>
            }
          />
        </div>
      )}
    </AppShell>
  );
}

/** The stream's raw phase and close reason (technical details); `count` is left out where raw events are not the viewer's business. */
export function Connection<T extends Framed>({ stream, count }: { stream: Stream<T>; count?: boolean }) {
  return (
    <output aria-label="Connection">
      {stream.phase}
      {stream.message && stream.phase !== "error" ? `: ${stream.message}` : ""}
      {count ? ` · ${stream.events.length} events` : ""}
    </output>
  );
}

/** What stays in the page header whatever is folded: the Reconnect button once the stream closes, and why it stopped. */
export function StreamAlert<T extends Framed>({ stream, reconnect }: { stream: Stream<T>; reconnect: () => void }) {
  return (
    <>
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

/**
 * A message box that posts once per submit: Enter sends, Shift+Enter starts a new line. No Stop button: a stop
 * goes through the chat (redesign §3.2). `pending`: sent texts not yet echoed (the chat shows its own in the stream).
 * `closed`: why it cannot send yet (input and Send disabled). `explain`: the words for a known refusal.
 */
export function Composer({
  label,
  post,
  pending = [],
  hint,
  closed,
  explain,
}: {
  label: string;
  post: (text: string) => Promise<PostResult>;
  pending?: string[];
  hint?: string;
  closed?: string;
  explain?: (r: Failed) => string | undefined;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy || closed) return;
    setBusy(true);
    setError("");
    void post(t).then((r) => {
      setBusy(false);
      if (r.ok) setText("");
      else setError(explain?.(r) ?? `Not delivered: ${r.status ? `${r.status} ` : ""}${r.error}`);
    });
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
  };
  const id = useId();
  return (
    <form className="pl-composer" aria-label={label} onSubmit={submit}>
      <label htmlFor={id} className="pl-sr">
        {label}
      </label>
      <div className="pl-composer-box">
        <textarea
          id={id}
          rows={1}
          value={text}
          placeholder={label}
          disabled={!!closed}
          aria-describedby={closed ? `${id}-closed` : undefined}
          onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
        <button type="submit" className="pl-send" aria-label="Send" disabled={busy || !!closed}>
          <Icon name="send" />
        </button>
      </div>
      {hint && (
        <p className="meta pl-composer-hint">
          <Icon name="hold" size="xs" />
          {hint}
        </p>
      )}
      {closed && (
        <p className="meta" id={`${id}-closed`}>
          {closed}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
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
