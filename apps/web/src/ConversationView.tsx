// The conversation view (S1-SYS-39, S1-SYS-49; v4 S1-SYS-77), the default for live and
// replay: the case header, one stream (the chat, the Guard cards and the call as call
// cards among them, stream.ts) and the Task details rail. Each line shows only what the
// listener heard (conversation.ts), with the speaker in its text ("You: …"), if
// only for screen readers. The six engineer lanes and the prompt drawer are
// behind ?view=engineer.
import { Fragment, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from "react";
import { from } from "./authority";
import { callHead, SIM_USER, simLabels, speakerName, type CallHead, type Line, type Parties } from "./conversation";
import { receipts, type Receipt as Tick } from "./fenceTicks";
import { Receipt } from "./live/Receipt";
import { statusView, statusWords } from "./outcome";
import type { Ev } from "./replay";
import { stream, type CallPart } from "./stream";
import { Chip } from "./ui/Chip";
import { EmptyState } from "./ui/EmptyState";
import { Icon } from "./ui/Icon";
import "./live/live.css";

const ENGINEER = "engineer";

/** The URL with ?view=engineer set or removed; every other parameter is kept. */
export function viewHref(search: string, engineer: boolean): string {
  const q = new URLSearchParams(search);
  if (engineer) q.set("view", ENGINEER);
  else q.delete("view");
  return `?${q.toString()}`;
}

/** The view, from ?view=, and a link to the other one (in place: the stream and the page state stay). */
export function useView() {
  const [engineer, setEngineer] = useState(() => new URLSearchParams(location.search).get("view") === ENGINEER);
  const href = viewHref(location.search, !engineer);
  const link = (
    <a
      href={href}
      onClick={(e) => {
        e.preventDefault();
        history.replaceState(null, "", href);
        setEngineer(!engineer);
      }}
    >
      {engineer ? "Conversation view" : "Engineer view"}
    </a>
  );
  return { engineer, link };
}

/** A column's sim label (I8, I11); nothing when no party in `labels` is simulated. */
export function SimNote({ labels }: { labels: string[] }) {
  if (labels.length === 0) return null;
  return (
    <p className="sim" aria-label="Simulated parties">
      {labels.join(" · ")}
    </p>
  );
}

/** The status line and, once session.ended arrives, the outcome banner. */
export function StatusBar({ events }: { events: Ev[] }) {
  const { line, outcome } = useMemo(() => statusView(events), [events]);
  return (
    <>
      <p className="status-line" role="status" aria-live="polite" aria-label="Status line">
        {line}
      </p>
      {outcome && (
        <section className={`outcome${outcome.verified ? " verified" : ""}`} aria-label="Outcome">
          <h2>{outcome.title}</h2>
          <p>
            Reason: {outcome.reason} · last case status: {outcome.status ?? "none"}
            {outcome.verdict ? ` · verifier: ${outcome.verdict}` : ""}
          </p>
        </section>
      )}
    </>
  );
}

/** The rail's folded technical part: the authority details and the run summary, as the caller gives them. */
export function TechDetails({ children }: { children: ReactNode }) {
  return (
    <details className="pl-card pl-tech">
      <summary>Technical details</summary>
      {children}
    </details>
  );
}

/** The case header's one tag: "Needs you" while a card waits for the principal, else Guard's last case status in words. */
function CaseTag({ events, input }: { events: Ev[]; input?: ChatInput }) {
  const status = useMemo(() => events.findLast((e) => from(e, "status.changed", ["guard"]))?.payload.status, [events]);
  if (!input?.recording && input?.cards.some((c) => c.status === "open")) {
    return (
      <Chip tone="you" className="pl-case-tag">
        <Icon name="you" size="xs" />
        Needs you
      </Chip>
    );
  }
  return status === undefined ? null : <Chip className="pl-case-tag">{statusWords(String(status))}</Chip>;
}

/**
 * The case (prototype v4): the header row (`head`, then the tag), the stream and composer, and the Task details rail
 * (`details`; below 1100px a drawer behind the header's button). `announce`: the stream is aria-live (live only: a
 * replay seek must not read out every line). The phone's sheet sits between the header and the composer (live.css).
 */
export function Panes({ events, p, announce, input, head, details }: { events: Ev[]; p: Parties; announce: boolean; input?: ChatInput; head: ReactNode; details: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const show = (on: boolean) => {
    setOpen(on);
    // The drawer takes focus when opened and gives it back to its button when closed.
    requestAnimationFrame(() => (on ? close : toggle).current?.focus());
  };
  // Escape closes the open drawer wherever the focus is.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && show(false);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <div className="pl-case" data-details={open ? "open" : undefined}>
      <div className="pl-casehead">
        {head}
        <CaseTag events={events} input={input} />
        <button type="button" ref={toggle} className="pl-details-toggle" aria-expanded={open} aria-controls={id} onClick={() => show(!open)}>
          Task details
        </button>
      </div>
      <Stream events={events} p={p} announce={announce} input={input} />
      <aside id={id} className="pl-details" aria-labelledby={`${id}-h`}>
        <div className="pl-details-head">
          <h2 id={`${id}-h`}>Task details</h2>
          <button type="button" ref={close} className="pl-details-close" onClick={() => show(false)}>
            Close
          </button>
        </div>
        {details}
      </aside>
    </div>
  );
}

// Follows the newest line while the list is scrolled to its end; once the reader scrolls up it stays put.
const AT_END_PX = 8;

/** `count` is the number of lines and items: a new one scrolls the list to its end while it follows. */
function Transcript({ name, announce, count, children }: { name: string; announce: boolean; count: number; children: ReactNode }) {
  const list = useRef<HTMLOListElement>(null);
  const [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    const el = list.current;
    if (following && el) el.scrollTop = el.scrollHeight;
  }, [following, count]);
  const onScroll = () => {
    const el = list.current;
    if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= AT_END_PX);
  };
  return (
    <>
      <ol ref={list} className="pl-tx" aria-label={`${name} transcript`} aria-live={announce ? "polite" : undefined} onScroll={onScroll}>
        {children}
      </ol>
      {!following && (
        <button type="button" className="pl-jump" onClick={() => setFollowing(true)}>
          Jump to latest
        </button>
      )}
    </>
  );
}

const RECEIPT: Record<Tick, string> = { pausing: "Pausing commitments…", read: "✓ Read by the agent" };

/** One heard line: yours in a bubble, the assistant's plain; on the call, each voice under its name; a call event centred. */
function TranscriptLine({ l, p, receipt }: { l: Line; p: Parties; receipt?: Tick }) {
  const name = speakerName(l.who, p);
  if (l.who === "call") {
    return (
      <li className="pl-line pl-line-call">
        <span className="pl-sr">{name}: </span>
        {l.text}
      </li>
    );
  }
  const onCall = l.who === "agent" || l.who === "rep";
  return (
    <li className={`pl-line pl-line-${l.who}`}>
      <div className="pl-line-body">
        <span className={onCall ? "pl-who" : "pl-sr"}>{name}</span>
        <span className="pl-sr">: </span>
        <p className={`pl-bubble${l.tag ? " pl-bubble-guard" : ""}`}>{l.text}</p>
        {l.interrupted && <span className="pl-line-meta"> — cut off</span>}
        {l.tag && (
          <span className="pl-line-meta pl-line-tag">
            {" "}
            <Icon name="guard" size="xs" />
            {l.tag}
          </span>
        )}
        {receipt && <span className={`pl-line-meta pl-receipt-${receipt}`}> {RECEIPT[receipt]}</span>}
      </div>
    </li>
  );
}

/** Session time, m:ss from the run's start (t_ms). */
const clock = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

/**
 * One part of a call: its header (the state and hold on the last part, "continues below" on the others) and its
 * heard lines in a "Call transcript" list. The header is aria-live off: a split is never read out, only new lines.
 */
function CallCard({ part, head, p }: { part: CallPart; head: CallHead; p: Parties }) {
  const id = useId();
  const latest = part.call === head.calls;
  const state = !part.last || part.call === 0 ? null : !latest || !head.open ? "Call ended" : head.calls > 1 ? `Call ${head.calls} of ${head.calls}` : "Connected";
  return (
    <div className="pl-call" role="group" aria-labelledby={id}>
      <div className="pl-call-h" aria-live="off">
        <span className="pl-call-ic">
          <Icon name="call" size="sm" />
        </span>
        <div className="pl-call-tt">
          <h3 id={id}>Call with the company</h3>
          <SimNote labels={simLabels(p)} />
          {!part.last && <p className="meta pl-call-cont">continues below</p>}
        </div>
        {state && <Chip>{state}</Chip>}
        {part.last && latest && head.holdSince !== null && (
          <Chip>
            <Icon name="hold" size="xs" />
            On hold since {clock(head.holdSince)}
          </Chip>
        )}
      </div>
      {part.part === 1 && (
        <div className="pl-call-about" aria-live="off">
          <p className="pl-privacy">
            <Icon name="guard" size="sm" />
            The phone voice speaks for you but never sees your limits.
          </p>
          <p className="pl-legend meta">
            <span className="pl-key-agent">Agent (phone voice)</span>
            <span className="pl-key-rep">{p.simRep ? "Rep (simulated)" : "Rep"}</span>
            <span className="pl-key-guard">Guard wording</span>
            <span className="pl-legend-end">Only what was heard</span>
          </p>
        </div>
      )}
      <ol className="pl-call-lines" aria-label="Call transcript">
        {part.lines.map((l) => (
          <TranscriptLine key={l.id} l={l} p={p} />
        ))}
      </ol>
    </div>
  );
}

/** A Guard card element, keyed, at its event's seq, with its status when known ("open": it waits for the principal). */
export type GuardCard = { seq: number; status?: string; el: ReactElement };
/** The chat's cards, unechoed sends and composer; `recording`: a replay's, whose composer is the "This is a recording" bar. */
export type ChatInput = { cards: GuardCard[]; pending: string[]; composer: ReactNode; recording?: boolean };

type Placed = { seq: number; key: string; el: ReactElement };

/**
 * The stream (stream.ts): your messages with their read receipts (fenceTicks.ts), the chat voice's heard lines, the
 * Guard cards, the call's parts and, at session.ended, the receipt; then the unechoed sends and the composer. Cards
 * and the receipt are aria-live off; a centred time is aria-hidden, so a new line is still one announcement.
 */
function Stream({ events, p, announce, input }: { events: Ev[]; p: Parties; announce: boolean; input?: ChatInput }) {
  const ticks = useMemo(() => receipts(events), [events]);
  const head = useMemo(() => callHead(events), [events]);
  const { outcome } = useMemo(() => statusView(events), [events]);
  const ended = outcome && events.findLast((e) => e.type === "session.ended" && e.actor === "kernel");
  const placed: Placed[] = [
    ...(input?.cards ?? []).map((c) => ({ seq: c.seq, key: `card:${c.el.key ?? c.seq}`, el: c.el })),
    ...(outcome && ended ? [{ seq: ended.seq, key: "outcome", el: <Receipt events={events} outcome={outcome} /> }] : []),
  ];
  const items = stream(events, placed);
  const count = items.reduce((n, i) => n + (i.kind === "call" ? i.part.lines.length : 1), 0);
  const empty = input && !input.recording ? "Tell ProxyLoop what you need, in your own words." : "Nothing said in the chat yet.";
  return (
    <section className="pl-chat" aria-label="Chat">
      <h2 className="pl-sr">Chat with ProxyLoop</h2>
      <p className="meta pl-private">
        <Icon name="private" size="xs" />
        Private: the rep never sees this chat
      </p>
      <SimNote labels={p.simUser ? [SIM_USER] : []} />
      {items.length === 0 && <EmptyState title={empty} />}
      <Transcript name="Chat" announce={announce} count={count}>
        {items.map((i) => {
          const key = i.kind === "line" ? i.line.id : i.kind === "item" ? i.item.key : `call:${i.part.call}.${i.part.part}`;
          return (
            <Fragment key={key}>
              {i.time && (
                <li className="pl-time" aria-hidden="true">
                  {i.time}
                </li>
              )}
              {i.kind === "line" ? (
                <TranscriptLine l={i.line} p={p} receipt={i.line.who === "you" ? ticks.get(i.line.id) : undefined} />
              ) : i.kind === "item" ? (
                <li className="pl-line-card" aria-live="off">
                  {i.item.el}
                </li>
              ) : (
                <li className="pl-line-callcard">
                  <CallCard part={i.part} head={head} p={p} />
                </li>
              )}
            </Fragment>
          );
        })}
      </Transcript>
      {input && input.pending.length > 0 && (
        <ul className="pl-pending" aria-label="Pending">
          {input.pending.map((text, i) => (
            <li key={i}>
              <p className="pl-bubble">{text}</p>
              <span className="pl-line-meta"> Sending…</span>
            </li>
          ))}
        </ul>
      )}
      <div className="pl-dock">{input?.composer}</div>
    </section>
  );
}
