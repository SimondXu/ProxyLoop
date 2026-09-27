// The live shell (?live=<run_id>): the replay's lanes, cards and drawer, fed by
// /ws/live instead of a loaded file, plus the user chat input, the authority
// strip and the approval cards. It shows only what events say. Models are chosen
// on the start page (?start); here RunSummary shows the ones session.started names.
import { useMemo, useRef, useState, type FormEvent } from "react";
import { Drawer, Lanes, RunSummary, useDrill } from "./App";
import { approvalCards, type CardStatus, type CardView, type Posting } from "./approval";
import { authorityStrip, type Strip } from "./authority";
import { parseEvent, unechoed, type Framed, type Sent, type Stream } from "./liveState";
import { postApproval, postMessage, type Decision, type PostResult } from "./liveApi";
import { indexEvents } from "./replay";
import { useEventStream } from "./useEventStream";

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
  const [sent, setSent] = useState<Sent[]>([]);

  const cards = useMemo(() => approvalCards(events, posts), [events, posts]);
  const strip = useMemo(() => authorityStrip(events), [events]);
  // Cards with a pending or ok post: a second click, even before a re-render, never POSTs again.
  const claimed = useRef(new Set<string>());
  const decide = (view: CardView, decision: Decision) => {
    const id = view.card.approval_id;
    if (claimed.current.has(id)) return;
    claimed.current.add(id);
    setPosts((m) => new Map(m).set(id, "pending"));
    void postApproval(runId, view.card, decision).then((r) => {
      if (!r.ok) claimed.current.delete(id); // a failed post may be clicked again, by hand
      setPosts((m) => new Map(m).set(id, r));
    });
  };
  const send = async (text: string) => {
    const after = stream.next;
    const r = await postMessage(runId, text);
    if (r.ok) setSent((s) => [...s, { text, after }]);
    return r;
  };
  const echoes = events.filter((e) => e.type === "user.msg").map((e) => ({ seq: e.seq, text: String(e.payload.text) }));

  return (
    <main>
      <header className="bar">
        <h1>ProxyLoop live · {runId}</h1>
        <Connection stream={stream} reconnect={reconnect} count />
        <label>
          <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
        </label>
      </header>
      <p className="meta">{ended ? "Run ended: the prompt drill-down reads prompts.jsonl." : PROMPTS_LATER}</p>
      <RunSummary events={events} />
      <AuthorityStrip a={strip} />
      {cards.length > 0 && (
        <section className="approvals" aria-label="Approvals">
          {cards.map((v) => (
            <Approval key={v.card.approval_id} view={v} decide={decide} fenced={strip.fences.length > 0} />
          ))}
        </section>
      )}
      <Composer label="Message to the agent" post={send} pending={unechoed(sent, echoes).map((s) => s.text)} />
      <Lanes shown={events} index={index} god={god} open={open} />
      {drill && <Drawer drill={drill} close={close} />}
    </main>
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

const STATUS: Record<CardStatus, string> = {
  open: "awaiting your decision",
  pending: "sending…",
  sent: "sent: waiting for the kernel's decision",
  stale: "stale",
  superseded: "superseded by a newer card for this offer",
  already_decided: "already decided: waiting for approval.decided",
  refused: "refused",
  granted: "decided: granted",
  denied: "decided: denied",
};

// A raised fence does not block the approval (guard.decide does not check fences);
// it holds the accept (ARCHITECTURE §9.4), so the card says so while it may still be decided.
const UNDECIDED: CardStatus[] = ["open", "pending", "sent"];

function Approval({ view, decide, fenced }: { view: CardView; decide: (v: CardView, d: Decision) => void; fenced: boolean }) {
  const { card, status, by, error, reason, slots } = view;
  const live = status === "open";
  return (
    <article className={`approval ${status}`} aria-label={`Approval ${card.approval_id}`}>
      <h2>Approval requested</h2>
      <pre aria-label="Readback">{card.readback_text}</pre>
      <p className="meta">
        offer {card.offer_ref} rev {card.revision} · epoch {card.authority_epoch} · terms {card.terms_hash.slice(0, 12)}
      </p>
      {slots ? (
        <ul aria-label="Read-back progress" className="slots">
          {slots.map((s) => (
            <li key={s.field} className={s.status}>
              {s.field}: {s.status}
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">no readback.updated for this offer revision yet</p>
      )}
      <p aria-label="Approval status">
        {STATUS[status]}
        {by ? ` by ${by}` : ""}
        {reason ? `: ${reason}` : ""}
      </p>
      {fenced && UNDECIDED.includes(status) && <p aria-label="Fence note">fence raised: the accept waits until it clears</p>}
      {error && <p role="alert">{error}</p>}
      <button type="button" disabled={!live} onClick={() => decide(view, "granted")}>
        Approve
      </button>
      <button type="button" disabled={!live} onClick={() => decide(view, "denied")}>
        Deny
      </button>
    </article>
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
  return (
    <form className="bar composer" aria-label={label} onSubmit={submit}>
      <input aria-label={label} placeholder={label} value={text} onChange={(e) => setText(e.target.value)} />
      <button type="submit" disabled={busy}>
        Send
      </button>
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
