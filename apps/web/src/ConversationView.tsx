// The conversation view (S1-SYS-39), the default for live and replay: a chat
// pane and a call pane that follow the newest line, the sim labels on every
// frame, the status line and the outcome banner. The six engineer lanes and the
// prompt drawer are behind ?view=engineer.
import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { conversation, simLabels, speakerName, type Line, type Parties } from "./conversation";
import { statusView } from "./outcome";
import type { Ev } from "./replay";

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

export function SimNote({ p }: { p: Parties }) {
  const labels = simLabels(p);
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

/**
 * The sticky header's shared part: the sim labels, the status line and the banner.
 * `p` comes from the whole log where it is known (the replay), so every frame is labelled (I11).
 */
export function Story({ events, p }: { events: Ev[]; p: Parties }) {
  return (
    <>
      <SimNote p={p} />
      <StatusBar events={events} />
    </>
  );
}

/** `announce`: the transcripts are aria-live (live mode only: a replay seek must not read out every line). */
export function Panes({ events, p, announce, composer }: { events: Ev[]; p: Parties; announce: boolean; composer?: ReactNode }) {
  const c = useMemo(() => conversation(events), [events]);
  const rep = p.simRep ? "Rep (simulated)" : "Rep";
  return (
    <div className="panes">
      <Pane name="Chat" title="Chat · You / Assistant" p={p} lines={c.chat} announce={announce}>
        {composer}
      </Pane>
      <Pane name="Call" title={`Call · Agent / ${rep} / Call`} p={p} lines={c.call} announce={announce} />
    </div>
  );
}

// Follows the newest line while the list is scrolled to its end; once the reader scrolls up it stays put.
const AT_END_PX = 8;

type PaneProps = { name: string; title: string; p: Parties; lines: Line[]; announce: boolean; children?: ReactNode };

function Pane({ name, title, p, lines, announce, children }: PaneProps) {
  const list = useRef<HTMLOListElement>(null);
  const [following, setFollowing] = useState(true);
  useLayoutEffect(() => {
    const el = list.current;
    if (following && el) el.scrollTop = el.scrollHeight;
  }, [following, lines.length]);
  const onScroll = () => {
    const el = list.current;
    if (el) setFollowing(el.scrollHeight - el.scrollTop - el.clientHeight <= AT_END_PX);
  };
  return (
    <section className="pane" aria-label={name}>
      <h2>{title}</h2>
      <SimNote p={p} />
      <ol ref={list} aria-label={`${name} transcript`} aria-live={announce ? "polite" : undefined} onScroll={onScroll}>
        {lines.map((l) => (
          <li key={l.seq} className={`line-${l.who}`}>
            <strong>
              {speakerName(l.who, p)}
              {l.disclosure ? " · AI disclosure (fixed text)" : ""}:
            </strong>{" "}
            {l.text}
            {l.interrupted ? " [interrupted]" : ""}
          </li>
        ))}
      </ol>
      {!following && (
        <button type="button" onClick={() => setFollowing(true)}>
          Jump to latest
        </button>
      )}
      {children}
    </section>
  );
}
