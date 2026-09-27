// The operator's start page (?start): a task, the rep mode and one model per
// lane, from GET /api/models only, then one POST /api/cases (start.ts, liveApi.ts).
import { useEffect, useRef, useState, type FormEvent } from "react";
import { csrfToken, getOptions, paths, startCase } from "./liveApi";
import { defaults, maybeStarted, parseOffer, START_LANES, startError, type Offer } from "./start";

const hasCookie = () => {
  try {
    return csrfToken(document.cookie, "start") !== null;
  } catch {
    return false; // a malformed cookie: the POST says so
  }
};

export function StartPage() {
  const [offer, setOffer] = useState<Offer | string | null>(null);
  const [task, setTask] = useState("");
  const [rep, setRep] = useState<"sim" | "human">("sim");
  const [models, setModels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<string | null>(null);
  const claimed = useRef(false); // a double click never starts twice

  useEffect(() => {
    void getOptions().then((r) => {
      const got = r.ok ? parseOffer(r.body) : r.error;
      setOffer(got);
      if (typeof got !== "string") {
        setTask(got.tasks[0] ?? "");
        setModels(defaults(got.options));
      }
    });
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (claimed.current || !task) return;
    claimed.current = true;
    setBusy(true);
    setError("");
    void startCase({ task_ref: task, models, rep }).then((r) => {
      if (!r.ok && maybeStarted(r)) {
        // Start stays disabled: a second click could start a second paid session.
        setError(`${startError(r)}. The session may have started: open the live page or reload`);
      } else if (!r.ok) {
        claimed.current = false; // a definite refusal, shown; a new start is the operator's click
        setBusy(false);
        setError(startError(r));
      } else if (rep === "sim") location.assign(paths.liveSession(r.caseId));
      else setStarted(r.caseId); // human: the rep's tab must be opened by a click
    });
  };

  return (
    <main>
      <header className="bar">
        <h1>ProxyLoop: start a live session</h1>
      </header>
      {!hasCookie() && (
        <p role="note" className="note">
          No operator cookie: <a href={paths.start}>open /start</a> first.
        </p>
      )}
      {offer === null && <p>Loading the options…</p>}
      {typeof offer === "string" && <p role="alert">Options unavailable: {offer}</p>}
      {offer !== null && typeof offer !== "string" && (
        <form className="start" aria-label="Start a session" onSubmit={submit}>
          <label>
            Task{" "}
            <select aria-label="Task" value={task} onChange={(e) => setTask(e.target.value)}>
              {offer.tasks.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Rep</legend>
            {(["sim", "human"] as const).map((m) => (
              <label key={m}>
                <input type="radio" name="rep" value={m} checked={rep === m} onChange={() => setRep(m)} /> {m}
              </label>
            ))}
          </fieldset>
          {START_LANES.map(({ lane, title }) => {
            const own = offer.options.filter((o) => o.lane === lane);
            return (
              <label key={lane}>
                {title}{" "}
                <select
                  aria-label={`${title} model`}
                  value={models[lane] ?? ""}
                  disabled={own.length === 0}
                  onChange={(e) => setModels((m) => ({ ...m, [lane]: e.target.value }))}
                >
                  {own.length === 0 && <option value="">none offered</option>}
                  {own.map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.label} · {o.model_id} · {o.endpoint}
                    </option>
                  ))}
                </select>
              </label>
            );
          })}
          <button type="submit" disabled={busy || !task}>
            Start
          </button>
          {offer.tasks.length === 0 && <p>No tasks offered.</p>}
          {error && <p role="alert">Not started: {error}</p>}
        </form>
      )}
      {started && (
        <p aria-label="Started">
          Case {started} started with a human rep. <a href={paths.repSession(started)} target="_blank" rel="noopener">Open the rep page</a>{" "}
          in a new tab, then <a href={paths.liveSession(started)}>open the live page</a>.
        </p>
      )}
    </main>
  );
}
