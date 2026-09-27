import { useEffect, useMemo, useState } from "react";
import { listBundles, loadPrompt, loadRun, type BundleInfo, type PromptRecord, type Run } from "./bundleSource";
import { indexEvents, LANES, laneOf, modelLabel, runHeader, shasOf, summary, type Ev, type Index, type Lane } from "./replay";
import { usePlayback, type Speed } from "./usePlayback";

export type Drill = { label: string; sha: string; record?: PromptRecord | null; note?: string };
export type Open = (label: string, sha: string) => void;

/** The prompt drill-down; `unavailable` explains why prompts cannot be loaded yet. */
export function useDrill(runId: string, unavailable?: string) {
  const [drill, setDrill] = useState<Drill | null>(null);
  const open: Open = (label, sha) => {
    if (unavailable) return setDrill({ label, sha, note: unavailable });
    setDrill({ label, sha });
    loadPrompt(runId, sha)
      .then((record) => setDrill((d) => (d?.sha === sha ? { ...d, record } : d)))
      .catch((e: unknown) => setDrill({ label: `${label}: ${String(e)}`, sha, record: null }));
  };
  return { drill, open, close: () => setDrill(null) };
}

export function App() {
  const [bundles, setBundles] = useState<BundleInfo[]>([]);
  const [runId, setRunId] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listBundles()
      .then((list) => {
        setBundles(list);
        setRunId(list[0]?.run_id ?? "");
      })
      .catch((e: unknown) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!runId) return;
    let live = true;
    loadRun(runId)
      .then((r) => live && setRun(r))
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [runId]);

  return (
    <main>
      <header className="bar">
        <h1>ProxyLoop replay</h1>
        <label>
          Run{" "}
          <select aria-label="Run" value={runId} onChange={(e) => setRunId(e.target.value)}>
            {bundles.map((b) => (
              <option key={b.run_id} value={b.run_id}>
                {b.run_id} {b.task_ref ?? ""} {b.complete ? "" : "(incomplete)"}
              </option>
            ))}
          </select>
        </label>
      </header>
      {error && <p role="alert">{error}</p>}
      {!error && bundles.length === 0 && <p>No bundles under PL_BUNDLE_DIR.</p>}
      {run && <Replay key={runId} runId={runId} run={run} />}
    </main>
  );
}

function Replay({ runId, run }: { runId: string; run: Run }) {
  const index = useMemo(() => indexEvents(run.events), [run]);
  const end = run.events.at(-1)?.t_ms ?? 0;
  const clock = usePlayback(end);
  const [god, setGod] = useState(false);
  const { drill, open, close } = useDrill(runId);

  const shown = run.events.filter((e) => e.t_ms <= clock.t);

  return (
    <>
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
        <label>
          <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
        </label>
      </section>
      <RunSummary events={run.events} />
      <Lanes shown={shown} index={index} god={god} open={open} />
      {drill && <Drawer drill={drill} close={close} />}
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
    <section className="run-head" aria-label="Run">
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
    </section>
  );
}

function Card({ e, index, open }: { e: Ev; index: Index; open: Open }) {
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
}

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
