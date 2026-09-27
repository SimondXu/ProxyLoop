import { memo, useCallback, useEffect, useMemo, useReducer, useState } from "react";
import { listBundles, loadPrompt, loadRun, type BundleInfo, type PromptRecord, type Run } from "./bundleSource";
import { endOf, indexEvents, LANES, laneOf, modelLabel, runHeader, selectRun, shasOf, summary, type Ev, type Index, type Lane } from "./replay";
import { parties } from "./conversation";
import { Panes, StatusBar, useView } from "./ConversationView";
import { honesty } from "./provenance";
import { AppShell } from "./shell/AppShell";
import { HonestyBand } from "./shell/HonestyBand";
import { Banner } from "./ui/Banner";
import { Card as Panel } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { usePlayback, type Speed } from "./usePlayback";

export type Drill = { label: string; sha: string; record?: PromptRecord | null; note?: string };
export type Open = (label: string, sha: string) => void;

/** The prompt drill-down; `unavailable` explains why prompts cannot be loaded yet. */
export function useDrill(runId: string, unavailable?: string) {
  const [drill, setDrill] = useState<Drill | null>(null);
  // Stable per run, so that the memoised cards do not re-render on every frame.
  const open: Open = useCallback(
    (label, sha) => {
      if (unavailable) return setDrill({ label, sha, note: unavailable });
      setDrill({ label, sha });
      loadPrompt(runId, sha)
        .then((record) => setDrill((d) => (d?.sha === sha ? { ...d, record } : d)))
        .catch((e: unknown) => setDrill({ label: `${label}: ${String(e)}`, sha, record: null }));
    },
    [runId, unavailable],
  );
  return { drill, open, close: () => setDrill(null) };
}

export function App() {
  const [bundles, setBundles] = useState<BundleInfo[]>([]);
  // A switch clears the run and the error at once; a late load for an earlier selection is dropped.
  const [{ runId, request, run, error }, dispatch] = useReducer(selectRun, {
    runId: "",
    request: 0,
    run: null,
    error: "",
  });

  useEffect(() => {
    listBundles()
      .then((list) => {
        setBundles(list);
        dispatch({ type: "select", runId: list[0]?.run_id ?? "" });
      })
      .catch((e: unknown) => dispatch({ type: "failed", request: 0, error: String(e) }));
  }, []);

  useEffect(() => {
    if (!runId) return;
    loadRun(runId)
      .then((r) => dispatch({ type: "loaded", request, run: r }))
      .catch((e: unknown) => dispatch({ type: "failed", request, error: String(e) }));
  }, [runId, request]);
  const { engineer, link } = useView();

  return (
    <AppShell>
      <header className="bar">
        <h1>ProxyLoop replay</h1>
        {link}
        <label>
          Run{" "}
          <select aria-label="Run" value={runId} onChange={(e) => dispatch({ type: "select", runId: e.target.value })}>
            {bundles.map((b) => (
              <option key={b.run_id} value={b.run_id}>
                {b.run_id} {b.task_ref ?? ""} {b.complete ? "" : "(incomplete)"}
              </option>
            ))}
          </select>
        </label>
      </header>
      {error && (
        <Banner tone="danger" role="alert">
          {error}
        </Banner>
      )}
      {!error && bundles.length === 0 && <EmptyState title="No recorded runs yet." />}
      {run && <Replay key={runId} runId={runId} run={run} engineer={engineer} />}
    </AppShell>
  );
}

function Replay({ runId, run, engineer }: { runId: string; run: Run; engineer: boolean }) {
  const index = useMemo(() => indexEvents(run.events), [run]);
  const end = useMemo(() => endOf(run.events), [run]);
  // From the whole log, not the time-filtered one: the sim labels are on every frame, also before session.started's t_ms (I11).
  const who = useMemo(() => parties(run.events), [run]);
  const h = useMemo(() => honesty(run.events), [run]);
  const clock = usePlayback(end);
  const [god, setGod] = useState(false);
  const { drill, open, close } = useDrill(runId);

  const shown = run.events.filter((e) => e.t_ms <= clock.t);

  return (
    <>
      <div className="pl-sticky">
        <HonestyBand h={h} />
        <section className="bar" aria-label="Controls">
          <button type="button" onClick={clock.toggle}>
            {clock.playing ? "Pause" : "Play"}
          </button>
          {([1, 4] as Speed[]).map((s) => (
            <button key={s} type="button" aria-pressed={clock.speed === s} onClick={() => clock.setSpeed(s)}>
              {s}×
            </button>
          ))}
          <input
            type="range"
            aria-label="Timeline"
            min={0}
            max={end}
            value={Math.round(clock.t)}
            onChange={(e) => clock.seek(Number(e.target.value))}
          />
          <output aria-label="Clock">
            {(clock.t / 1000).toFixed(1)} s / {(end / 1000).toFixed(1)} s · {shown.length}/{run.events.length} events
          </output>
          {engineer && (
            <label>
              <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
            </label>
          )}
        </section>
        <StatusBar events={shown} />
      </div>
      <RunSummary events={run.events} />
      {engineer ? (
        <>
          <Lanes shown={shown} index={index} god={god} open={open} />
          {drill && <Drawer drill={drill} close={close} />}
        </>
      ) : (
        <Panes events={shown} p={who} announce={false} />
      )}
    </>
  );
}

/** The replay lanes; the live shell renders the same ones over the WebSocket. */
export function Lanes({ shown, index, god, open }: { shown: Ev[]; index: Index; god: boolean; open: Open }) {
  const lanes = LANES.filter((l) => god || l.id !== "world");
  const byLane = new Map<Lane, Ev[]>(lanes.map((l) => [l.id, []]));
  for (const e of shown) {
    const lane = laneOf(e);
    if (lane) byLane.get(lane)?.push(e);
  }
  return (
    <div className="lanes">
      {lanes.map((l) => (
        <section key={l.id} className="lane" aria-label={l.title}>
          <h2>{l.title}</h2>
          <ol>
            {byLane.get(l.id)?.map((e) => (
              <Card key={e.seq} e={e} index={index} open={open} />
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

export function RunSummary({ events }: { events: Ev[] }) {
  const head = useMemo(() => runHeader(events), [events]);
  if (!head) return <p className="run-head">No session.started event in this run.</p>;
  return (
    <Panel className="run-head" aria-label="Run">
      <p>
        {head.run_id} · task {head.task_ref} · split {head.split} · contract {head.contract_version}
      </p>
      <ul aria-label="Models">
        {head.models.map((m) => (
          <li key={m.role}>
            {m.role}: <strong>{m.kind}</strong> {m.model_id}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// Memoised: each frame re-renders the lanes, not every card and its payload JSON.
const Card = memo(function Card({ e, index, open }: { e: Ev; index: Index; open: Open }) {
  const label = e.type === "fast.sentence" ? modelLabel(e, index) : null;
  return (
    <li>
      <article className={`card ${e.type.replaceAll(".", "-")}`} aria-label={`${e.type} #${e.seq}`}>
        <p className="meta">
          {(e.t_ms / 1000).toFixed(2)} s · {e.type} · {e.actor}
        </p>
        <p>{summary(e)}</p>
        {label && (
          <p className="model">
            model: {label.model} · {label.adapter}
          </p>
        )}
        {shasOf(e).map((s) => (
          <button key={s.label} type="button" onClick={() => open(`${e.type} #${e.seq} ${s.label}`, s.sha)}>
            {s.label}
          </button>
        ))}
        <details>
          <summary>payload</summary>
          <pre>{JSON.stringify(e.payload, null, 2)}</pre>
        </details>
      </article>
    </li>
  );
});

export function Drawer({ drill, close }: { drill: Drill; close: () => void }) {
  return (
    <aside className="drawer" role="dialog" aria-label="Prompt drill-down">
      <button type="button" onClick={close}>
        Close
      </button>
      <h2>{drill.label}</h2>
      <p className="meta">sha {drill.sha}</p>
      {drill.note && <p>{drill.note}</p>}
      {!drill.note && drill.record === undefined && <p>Loading…</p>}
      {!drill.note && drill.record === null && <p>Not in prompts.jsonl.</p>}
      {drill.record && (
        <>
          <p className="meta">kind {drill.record.kind} (verbatim from prompts.jsonl)</p>
          <pre aria-label="Prompt content">{drill.record.content}</pre>
        </>
      )}
    </aside>
  );
}
