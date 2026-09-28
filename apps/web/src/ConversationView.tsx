// The conversation view (S1-SYS-39, S1-SYS-49), the default for live and
// replay: the chat and call columns (redesign §3.2), each following its newest
// line, the status line and the outcome banner. Each line shows only what the
// listener heard (conversation.ts), with the speaker in its text ("You: …"), if
// only for screen readers. The six engineer lanes and the prompt drawer are
// behind ?view=engineer.
import { useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactElement, type ReactNode } from "react";
import { callHead, conversation, SIM_USER, simLabels, speakerName, type Line, type Parties } from "./conversation";
import { receipts, type Receipt as Tick } from "./fenceTicks";
import { Receipt } from "./live/Receipt";
import { statusView } from "./outcome";
import { timeline } from "./timeline";
import type { Ev } from "./replay";
import { BrandMark } from "./ui/BrandMark";
import { Card } from "./ui/Card";
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

type Tab = "chat" | "call" | "steps";
const WIDE = "(min-width: 761px)";
const onWide = (f: () => void) => {
  const m = matchMedia(WIDE);
  m.addEventListener("change", f);
  return () => m.removeEventListener("change", f);
};
const TABS: [Tab, string][] = [
  ["chat", "Chat"],
  ["call", "Call"],
  ["steps", "Steps"],
];

/**
 * The chat and call columns, and the live page's rail when given. `announce`:
 * the transcripts are aria-live (live mode only: a replay seek must not read out every line).
 * With a rail, the tabs (redesign §3.6; CSS shows them only below 1181px) pick the column in view,
 * with a dot on a tab that got new items while out of view.
 */
export function Panes({ events, p, announce, input, rail }: { events: Ev[]; p: Parties; announce: boolean; input?: ChatInput; rail?: ReactNode }) {
  const c = useMemo(() => conversation(events), [events]);
  const steps = useMemo(() => timeline(events).length, [events]);
  const [picked, setTab] = useState<Tab>("chat");
  // Above 760px the chat is always in view, so its tab is the call's.
  const wide = useSyncExternalStore(onWide, () => matchMedia(WIDE).matches);
  const tab = wide && picked === "chat" ? "call" : picked;
  const counts: Record<Tab, number> = { chat: c.chat.length + (input?.cards.length ?? 0), call: c.call.length, steps };
  const [seen, setSeen] = useState<Record<Tab, number>>({ chat: 0, call: 0, steps: 0 });
  const pick = (t: Tab) => {
    setSeen((s) => ({ ...s, [tab]: counts[tab], [t]: counts[t] }));
    setTab(t);
  };
  return (
    <div className={`pl-work${rail ? " pl-work-rail" : ""}`} data-tab={rail ? tab : undefined}>
      {rail && (
        <div className="pl-tabs" role="group" aria-label="Show">
          {TABS.map(([t, name]) => (
            <button key={t} type="button" className={`pl-tab-${t}`} aria-pressed={t === tab} onClick={() => pick(t)}>
              {name}
              {t !== tab && counts[t] > seen[t] && (
                <span className="pl-dot">
                  <span className="pl-sr"> (new)</span>
                </span>
              )}
            </button>
          ))}
        </div>
      )}
      <ChatPanel events={events} lines={c.chat} p={p} announce={announce} input={input} />
      <CallPanel events={events} lines={c.call} p={p} announce={announce} />
      {rail && (
        <aside className="pl-rail" aria-label="What the agent is doing">
          {rail}
        </aside>
      )}
    </div>
  );
}

// Follows the newest line while the list is scrolled to its end; once the reader scrolls up it stays put.
const AT_END_PX = 8;

/** `count` is the number of items: a new one scrolls the list to its end while it follows. */
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
const AVATAR: Partial<Record<Line["who"], string>> = { agent: "AI", rep: "R" };

/** One heard line: ours (you, the agent) on the right, the other side's on the left, a call event centred. */
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
  const mine = l.who === "you";
  return (
    <li className={`pl-line pl-line-${l.who}`}>
      {!mine && (
        // The initials are CSS content: decorative, and never part of the line's text.
        <span className="pl-av" data-av={AVATAR[l.who]} aria-hidden="true">
          {!AVATAR[l.who] && <BrandMark />}
        </span>
      )}
      <div className="pl-line-body">
        <span className={mine ? "pl-sr" : "pl-who"}>{name}</span>
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

/** A Guard card element, keyed, at its event's seq. */
export type GuardCard = { seq: number; el: ReactElement };
/** The live page's part of the chat: the Guard cards, the unechoed sends and the composer. */
export type ChatInput = { cards: GuardCard[]; pending: string[]; composer: ReactNode };

type ColumnProps = { events: Ev[]; lines: Line[]; p: Parties; announce: boolean };

/**
 * The chat: your messages with their read receipts (fenceTicks.ts), the chat
 * voice's heard lines, and the Guard cards in event order among them; at
 * session.ended, the receipt (live/Receipt.tsx), in live and replay alike. A card is
 * Guard's, not the agent's: its own "Guard card · …" line, no avatar.
 */
function ChatPanel({ events, lines, p, announce, input }: ColumnProps & { input?: ChatInput }) {
  const ticks = useMemo(() => receipts(events), [events]);
  const { outcome } = useMemo(() => statusView(events), [events]);
  const ended = outcome && events.findLast((e) => e.type === "session.ended" && e.actor === "kernel");
  const items = [
    ...lines.map((l) => ({ seq: l.seq, el: <TranscriptLine key={l.id} l={l} p={p} receipt={l.who === "you" ? ticks.get(l.id) : undefined} /> })),
    ...(input?.cards ?? []).map((c) => ({
      seq: c.seq,
      el: (
        <li key={c.el.key ?? c.seq} className="pl-line-card" aria-live="off">
          {c.el}
        </li>
      ),
    })),
    ...(outcome && ended
      ? [
          {
            seq: ended.seq,
            el: (
              <li key="outcome" className="pl-line-card" aria-live="off">
                <Receipt events={events} outcome={outcome} />
              </li>
            ),
          },
        ]
      : []),
  ].sort((a, b) => a.seq - b.seq);
  return (
    <Card className="pl-col pl-col-chat" aria-label="Chat">
      <div className="pl-colhead">
        <h2>Chat with ProxyLoop</h2>
        <p className="meta">
          <Icon name="private" size="xs" />
          Private: the rep never sees this chat
        </p>
        <SimNote labels={p.simUser ? [SIM_USER] : []} />
      </div>
      {items.length === 0 && <EmptyState title={input ? "Tell ProxyLoop what you need, in your own words." : "Nothing said in the chat yet."} />}
      <Transcript name="Chat" announce={announce} count={items.length}>
        {items.map((i) => i.el)}
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
      {input?.composer}
    </Card>
  );
}

/** Session time, m:ss from the run's start (t_ms). */
const clock = (ms: number) => `${Math.floor(ms / 60_000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, "0")}`;

/** The call: the cp lane as heard, the call's state and hold (callHead), and the Guard wording's tags. */
function CallPanel({ events, lines, p, announce }: ColumnProps) {
  const head = useMemo(() => callHead(events), [events]);
  const state = head.calls === 0 ? null : !head.open ? "Call ended" : head.calls > 1 ? `Call ${head.calls} of ${head.calls}` : "Connected";
  return (
    <Card className="pl-col pl-col-call" aria-label="Call">
      <div className="pl-colhead">
        <div className="pl-colhead-row">
          <h2>
            <Icon name="call" size="sm" />
            Call with the company
          </h2>
          {state && <Chip>{state}</Chip>}
          {head.holdSince !== null && (
            <Chip tone="attn">
              <Icon name="hold" size="xs" />
              On hold since {clock(head.holdSince)}
            </Chip>
          )}
        </div>
        <SimNote labels={simLabels(p)} />
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
      {lines.length === 0 && <EmptyState title="No call yet. The agent calls once it has what it needs from you." />}
      <Transcript name="Call" announce={announce} count={lines.length}>
        {lines.map((l) => (
          <TranscriptLine key={l.id} l={l} p={p} />
        ))}
      </Transcript>
    </Card>
  );
}
