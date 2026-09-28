// The case's steps (redesign §3.0), display only: phase.ts reads Guard's
// status.changed and the kernel's session.ended, nothing else.
import { useMemo } from "react";
import { phase } from "../phase";
import type { Ev } from "../replay";
import { Chip } from "../ui/Chip";
import "./PhaseStepper.css";

export function PhaseStepper({ events }: { events: Ev[] }) {
  const ph = useMemo(() => phase(events), [events]);
  return (
    <div className="pl-phase">
      <ol className="pl-stepper" aria-label="Case progress">
        {ph.steps.map((s) => (
          <li key={s.label} className={`pl-step-${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
            <span className="pl-step-dot" aria-hidden="true" />
            {s.label}
            {(s.state === "done" || s.state === "skipped") && <span className="pl-sr"> ({s.state})</span>}
            {s.state === "current" && ph.note && <span className="meta"> · {ph.note}</span>}
          </li>
        ))}
      </ol>
      {ph.raw && <Chip>status {ph.raw}</Chip>}
    </div>
  );
}
