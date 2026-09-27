// The live shell (?live=<run_id>): the replay's lanes, cards and drawer, fed by
// /ws/live instead of a loaded file, plus the user chat input, the approval
// cards and the per-lane model dropdowns. It shows only what events say.
import { useMemo, useState, type FormEvent } from "react";
import { Drawer, Lanes, RunSummary, useDrill } from "./App";
import { approvalCards, type CardStatus, type CardView, type Posting } from "./approval";
import { MODEL_LANES, realHttpModels, unechoed, type Sent, type Stream } from "./liveState";
import { postApproval, postMessage, type Decision, type PostResult } from "./liveApi";
import { indexEvents, type Ev } from "./replay";
import { useEventStream } from "./useEventStream";

const PROMPTS_LATER = "Prompts are served only after the run ends (session.ended); open this again then.";

export function Live({ runId }: { runId: string }) {
  const { stream, reconnect } = useEventStream("live", runId);
  const events = stream.events;
  const index = useMemo(() => indexEvents(events), [events]);
  const ended = events.some((e) => e.type === "session.ended");
  const { drill, open, close } = useDrill(runId, ended ? undefined : PROMPTS_LATER);
  const [god, setGod] = useState(false);
  const [posts, setPosts] = useState<ReadonlyMap<string, Posting>>(new Map());
  const [sent, setSent] = useState<Sent[]>([]);

  const cards = useMemo(() => approvalCards(events, posts), [events, posts]);
  const decide = (view: CardView, decision: Decision) => {
    const id = view.card.approval_id;
    setPosts((m) => new Map(m).set(id, "pending"));
    void postApproval(runId, view.card, decision).then((r) => setPosts((m) => new Map(m).set(id, r)));
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
      <p className="meta">{ended ? "Run ended: prompt drill-down is available." : PROMPTS_LATER}</p>
      <RunSummary events={events} />
      <ModelPickers events={events} />
      {cards.length > 0 && (
        <section className="approvals" aria-label="Approvals">
          {cards.map((v) => (
            <Approval key={v.card.approval_id} view={v} decide={decide} />
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
export function Connection({ stream, reconnect, count }: { stream: Stream; reconnect: () => void; count?: boolean }) {
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

function ModelPickers({ events }: { events: Ev[] }) {
  const { options, configured } = useMemo(() => realHttpModels(events), [events]);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  return (
    <section className="bar" aria-label="Models per lane">
      {MODEL_LANES.map(({ role, title }) => (
        <label key={role}>
          {title}{" "}
          {options.length === 0 ? (
            <select aria-label={`${title} model`} disabled>
              <option>no real_http model</option>
            </select>
          ) : (
            <select
              aria-label={`${title} model`}
              value={chosen[role] ?? configured[role] ?? options[0]}
              onChange={(e) => setChosen((c) => ({ ...c, [role]: e.target.value }))}
            >
              {options.map((id) => (
                <option key={id}>{id}</option>
              ))}
            </select>
          )}
        </label>
      ))}
      <span className="meta">Only real_http models. The choice is local: no session-start call exists yet.</span>
    </section>
  );
}

const STATUS: Record<CardStatus, string> = {
  open: "awaiting your decision",
  pending: "sending…",
  sent: "sent: waiting for the kernel's decision",
  stale: "stale: the authority epoch moved past this card",
  superseded: "superseded by a newer card for this offer",
  already_decided: "already decided: waiting for approval.decided",
  granted: "decided: granted",
  denied: "decided: denied",
};

function Approval({ view, decide }: { view: CardView; decide: (v: CardView, d: Decision) => void }) {
  const { card, status, by, error } = view;
  const live = status === "open";
  return (
    <article className={`approval ${status}`} aria-label={`Approval ${card.approval_id}`}>
      <h2>Approval requested</h2>
      <pre aria-label="Readback">{card.readback_text}</pre>
      <p className="meta">
        offer {card.offer_ref} rev {card.revision} · epoch {card.authority_epoch} · terms {card.terms_hash.slice(0, 12)}
      </p>
      <p aria-label="Approval status">
        {STATUS[status]}
        {by ? ` by ${by}` : ""}
      </p>
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
