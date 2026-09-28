// The replay's engineer view (?view=engineer, redesign §3.5), loaded lazily:
// the status line and outcome, the run header, the events count, the lanes
// over the events up to the clock, and the prompt drill-down.
import { useMemo } from "react";
import { Drawer, Lanes, RunSummary, useDrill } from "../App";
import { StatusBar } from "../ConversationView";
import { indexEvents, type Ev } from "../replay";

type Props = { runId: string; events: Ev[]; shown: Ev[]; god: boolean };

export default function EngineerReplay({ runId, events, shown, god }: Props) {
  const index = useMemo(() => indexEvents(events), [events]);
  const { drill, open, close } = useDrill(runId);
  return (
    <>
      <StatusBar events={shown} />
      <RunSummary events={events} />
      <p className="meta" aria-label="Events shown">
        {shown.length}/{events.length} events
      </p>
      <Lanes shown={shown} index={index} god={god} open={open} />
      {drill && <Drawer drill={drill} close={close} />}
    </>
  );
}
