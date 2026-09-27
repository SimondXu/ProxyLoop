// The operator's start page (?start): a task, the rep mode and one model per
// lane, from GET /api/models only, then one POST /api/cases (start.ts, liveApi.ts).
import { useEffect, useRef, useState, type FormEvent } from "react";
import { csrfToken, getOptions, paths, startCase } from "./liveApi";
import { AppShell } from "./shell/AppShell";
import { defaults, maybeStarted, parseOffer, START_LANES, startError, type Offer } from "./start";
import { Banner } from "./ui/Banner";
import { Button } from "./ui/Button";
import "./ui/Card.css"; // the form and the started note are cards
import { EmptyState } from "./ui/EmptyState";
import { Skeleton } from "./ui/Skeleton";

/** Whether the operator's CSRF cookie is there. A malformed one is there: no "open /start" note, and the POST says why (#173 N-4). */
const hasCookie = () => {
  try {
    return csrfToken(document.cookie, "start") !== null;
  } catch {
    return true;
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
    <AppShell>
      <header className="bar">
        <h1>ProxyLoop: start a live session</h1>
      </header>
      {!hasCookie() && (
        <Banner tone="attn" role="note">
          No operator cookie: <a href={paths.start}>open /start</a> first.
        </Banner>
      )}
      {offer === null && <Skeleton label="Loading the options…" />}
      {typeof offer === "string" && (
        <Banner tone="danger" role="alert">
          Options unavailable: {offer}
        </Banner>
      )}
      {offer !== null && typeof offer !== "string" && (
        <form className="pl-card start" aria-label="Start a session" onSubmit={submit}>
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
          <Button variant="primary" type="submit" disabled={busy || !task}>
            Start
          </Button>
          {offer.tasks.length === 0 && <EmptyState title="No tasks offered." />}
          {error && (
            <Banner tone="danger" role="alert">
              Not started: {error}
            </Banner>
          )}
        </form>
      )}
      {started && (
        <p className="pl-card" aria-label="Started">
          Case {started} started with a human rep. <a href={paths.repSession(started)} target="_blank" rel="noopener">Open the rep page</a>{" "}
          in a new tab, then <a href={paths.liveSession(started)}>open the live page</a>.
        </p>
      )}
    </AppShell>
  );
}
