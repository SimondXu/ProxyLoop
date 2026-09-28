// One recorded run (`?run=<id>`, redesign §3.4): the Live page's components,
// read-only, over the events up to the playback clock. It opens at the end, so
// the cards show their final state and the receipt is in view. The composer is
// the "This is a recording" bar, and every card's buttons are disabled: nothing
// here posts. The band, the sim labels and the title come from the full log, so
// every frame is labelled, also before session.started's t_ms (I11).
import { lazy, Suspense, useDeferredValue, useEffect, useMemo, useState } from "react";
import { RunSummary } from "../App";
import { approvalCards, type Posting } from "../approval";
import { authorityStrip } from "../authority";
import { loadRun, type Run } from "../bundleSource";
import { parties } from "../conversation";
import { Panes, useView } from "../ConversationView";
import { AgentRail } from "../live/AgentRail";
import { ApprovalCard } from "../live/ApprovalCard";
import { LimitsCard } from "../live/LimitsCard";
import { mandateCards } from "../mandate";
import { honesty } from "../provenance";
import { endOf } from "../replay";
import { HonestyBand } from "../shell/HonestyBand";
import { PhaseStepper } from "../shell/PhaseStepper";
import { taskName } from "../start";
import { timeline } from "../timeline";
import { Banner } from "../ui/Banner";
import { Skeleton } from "../ui/Skeleton";
import { usePlayback } from "../usePlayback";
import { chapters, cutoff, marks } from "./marks";
import { PlaybackBar } from "./PlaybackBar";
import "./replay.css";

const Engineer = lazy(() => import("./EngineerReplay"));
const NO_POSTS = new Map<string, Posting>();
const noop = () => undefined;

export function ReplayPage({ runId }: { runId: string }) {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    loadRun(runId)
      .then((r) => current && setRun(r))
      .catch((e: unknown) => current && setError(String(e)));
    return () => {
      current = false;
    };
  }, [runId]);
  if (error) {
    return (
      <Banner tone="err" role="alert">
        {error}
      </Banner>
    );
  }
  return run ? <Recording runId={runId} run={run} /> : <Skeleton label="Loading the run…" />;
}

function Recording({ runId, run }: { runId: string; run: Run }) {
  const events = run.events;
  const end = useMemo(() => endOf(events), [events]);
  const clock = usePlayback(end);
  // The slider moves at once; the page follows when React has time, and re-derives only when an event enters or leaves.
  const t = useDeferredValue(clock.t);
  const times = useMemo(() => events.map((e) => e.t_ms).sort((a, b) => a - b), [events]);
  const cut = cutoff(times, t);
  const shown = useMemo(() => events.filter((e) => e.t_ms <= cut), [events, cut]);

  const who = useMemo(() => parties(events), [events]);
  const h = useMemo(() => honesty(events), [events]);
  const steps = useMemo(() => timeline(events), [events]);
  const found = useMemo(() => marks(events, steps), [events, steps]);
  const chs = useMemo(() => chapters(steps, found), [steps, found]);
  const cards = useMemo(() => approvalCards(shown, NO_POSTS), [shown]);
  const mandates = useMemo(() => mandateCards(shown, NO_POSTS), [shown]);
  const strip = useMemo(() => authorityStrip(shown), [shown]);
  const { engineer, link } = useView();
  const [god, setGod] = useState(false);

  const start = events.find((e) => e.type === "session.started" && e.actor === "kernel");
  // The Live page's Guard cards in event order; a fieldset disables their buttons.
  const guardCards = [
    ...mandates.map((v) => ({
      seq: v.seq,
      el: (
        <fieldset key={`m:${v.mandate.mandate_id}`} className="pl-rec-card" disabled>
          <LimitsCard view={v} events={shown} decide={noop} />
        </fieldset>
      ),
    })),
    ...cards.map((v) => ({
      seq: v.seq,
      el: (
        <fieldset key={`a:${v.card.approval_id}`} className="pl-rec-card" disabled>
          <ApprovalCard
            view={v}
            events={shown}
            mandates={mandates}
            fenced={strip.fences.length > 0}
            caseStatus={strip.status}
            decide={noop}
          />
        </fieldset>
      ),
    })),
  ].sort((a, b) => a.seq - b.seq);

  return (
    <div className={engineer ? "pl-replay" : "pl-live pl-replay"}>
      <div className="pl-sticky">
        <div className="pl-replay-band">
          <p className="pl-replay-tag">Replay of a recorded run</p>
          <HonestyBand h={h} />
        </div>
        <header className="bar">
          <h1>{start ? taskName(String(start.payload.task_ref)) : "Recorded run"}</h1>
          <span className="meta pl-runid">{runId}</span>
          <PhaseStepper events={shown} />
          {engineer && link}
          {engineer && (
            <label>
              <input type="checkbox" checked={god} onChange={(e) => setGod(e.target.checked)} /> God-view
            </label>
          )}
        </header>
      </div>
      {engineer ? (
        <Suspense fallback={<Skeleton label="Loading the engineer view…" />}>
          <Engineer runId={runId} events={events} shown={shown} god={god} />
        </Suspense>
      ) : (
        <Panes
          events={shown}
          p={who}
          announce={false}
          input={{
            cards: guardCards,
            pending: [],
            recording: true,
            composer: <p className="pl-recording">This is a recording: nothing here is sent, and no card can be clicked.</p>,
          }}
          rail={
            <>
              <AgentRail events={shown} cards={cards} mandates={mandates} />
              <RunSummary events={events} />
              {link}
            </>
          }
        />
      )}
      <PlaybackBar clock={clock} end={end} marks={found} chapters={chs} />
    </div>
  );
}
