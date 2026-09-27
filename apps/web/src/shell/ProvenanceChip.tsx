// Which kind of model ran (redesign §3.0): from session.started's per-role
// ref.kind. A scripted run is hatched; nothing here can hide the chip.
import { LIVE, type Chip as ChipView } from "../provenance";
import { Chip } from "../ui/Chip";
import "./ProvenanceChip.css";

export function ProvenanceChip({ chip }: { chip: ChipView }) {
  return (
    <details className="pl-provenance">
      <summary>
        <Chip tone={chip.scripted ? "sim" : chip.label === LIVE ? "agent" : "neutral"}>{chip.label}</Chip>
      </summary>
      <ul aria-label="Model kinds">
        {chip.roles.map((r) => (
          <li key={r.role}>
            {r.role}: {r.label}
          </li>
        ))}
      </ul>
    </details>
  );
}
