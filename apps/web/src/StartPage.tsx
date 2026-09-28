// The operator's start page (?start; redesign §3.1): a task, the rep mode and one model per
// lane, from GET /api/models only, then one POST /api/cases (start.ts, liveApi.ts).
import { useEffect, useRef, useState, type FormEvent } from "react";
import { csrfToken, getOptions, paths, startCase } from "./liveApi";
import { AppShell } from "./shell/AppShell";
import { defaults, maybeStarted, parseOffer, START_LANES, startError, taskName, type Offer } from "./start";
import "./StartPage.css";
import { Banner } from "./ui/Banner";
import { Button } from "./ui/Button";
import "./ui/Card.css"; // the setup boxes and the started note are cards
import { EmptyState } from "./ui/EmptyState";
import { Icon } from "./ui/Icon";
import { Skeleton } from "./ui/Skeleton";
import { useRoleCard, YourRole } from "./YourRole";

/** Whether the operator's CSRF cookie is there. A malformed one is there: no "open /start" note, and the POST says why (#173 N-4). */
const hasCookie = () => {
  try {
    return csrfToken(document.cookie, "start") !== null;
  } catch {
    return true;
  }
};

const REP_MODES = [
  { mode: "sim", title: "Simulated rep", hint: "" },
  { mode: "human", title: "A person", hint: "(opens a rep page)" },
] as const;

export function StartPage() {
  const [offer, setOffer] = useState<Offer | string | null>(null);
  const [task, setTask] = useState("");
  const [rep, setRep] = useState<"sim" | "human">("sim");
  const [models, setModels] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [started, setStarted] = useState<string | null>(null);
  const claimed = useRef(false); // a double click never starts twice
  const role = useRoleCard("task", task); // the chosen task's principal: the person who plays it

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
      <div className="pl-start-hero">
        <span className="pl-start-kicker">New case</span>
        <h1>What should ProxyLoop handle?</h1>
        <p>Pick a task. ProxyLoop chats with you first, calls the (simulated) company, and asks before anything binding happens.</p>
      </div>
      {!hasCookie() && (
        <Banner tone="over" role="note">
          No operator cookie: <a href={paths.start}>open /start</a> first.
        </Banner>
      )}
      {offer === null && (
        <div className="pl-card">
          <Skeleton label="Loading the options…" />
        </div>
      )}
      {typeof offer === "string" && (
        <Banner tone="err" role="alert">
          Options unavailable: {offer}
        </Banner>
      )}
      {offer !== null && typeof offer !== "string" && (
        <form className="pl-start" aria-label="Start a session" onSubmit={submit}>
          {offer.tasks.length === 0 ? (
            <EmptyState title="No tasks offered." />
          ) : (
            <div className="pl-start-main">
              <div className="pl-tasks" role="radiogroup" aria-label="Task">
                {offer.tasks.map((t) => (
                  <label key={t} className="pl-task">
                    <input type="radio" name="task" value={t} checked={task === t} onChange={() => setTask(t)} />
                    <span className="pl-task-card">
                      <span className="pl-task-name">{taskName(t)}</span> <code>{t}</code>
                    </span>
                  </label>
                ))}
              </div>
              {task && (
                <section className="pl-card pl-role" aria-label="Your role">
                  <h2>Your role</h2>
                  <p className="meta">You play the account holder in the chat. This is what they know and want.</p>
                  <YourRole card={role} />
                </section>
              )}
            </div>
          )}
          <div className="pl-start-setup">
            <div className="pl-card">
              <h2 id="pl-rep-title">Who plays the company's rep?</h2>
              <div className="pl-seg" role="radiogroup" aria-labelledby="pl-rep-title">
                {REP_MODES.map(({ mode, title, hint }) => (
                  <label key={mode}>
                    <input type="radio" name="rep" value={mode} checked={rep === mode} onChange={() => setRep(mode)} />
                    {title} {hint && <small>{hint}</small>}
                  </label>
                ))}
              </div>
            </div>
            <p className="pl-card pl-start-honest">
              <Icon name="simulated" size="sm" />
              <span>
                The company is simulated and no real company is called; the rep is simulated unless a person plays it. A run with
                live models calls paid model APIs, and each run's cost appears on its receipt.
              </span>
            </p>
            <details className="pl-card pl-start-adv">
              <summary>Advanced: models</summary>
              {START_LANES.map(({ lane, title }) => {
                const own = offer.options.filter((o) => o.lane === lane);
                return (
                  <label key={lane} className="pl-field">
                    {title}
                    <select
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
            </details>
            <Button variant="primary" type="submit" className="pl-start-go" disabled={busy || !task}>
              Start the case <span aria-hidden="true">→</span>
            </Button>
            {error && (
              <Banner tone="err" role="alert">
                Not started: {error}
              </Banner>
            )}
          </div>
        </form>
      )}
      {started && (
        <section className="pl-card pl-started" aria-label="Started">
          <p>Case {started} started with a human rep. Open the rep page in a new tab first, then the live page.</p>
          <a className="pl-started-link" href={paths.repSession(started)} target="_blank" rel="noopener">
            Open the rep page (new tab)
          </a>
          <a className="pl-started-link" href={paths.liveSession(started)}>
            Open the live page
          </a>
        </section>
      )}
    </AppShell>
  );
}
