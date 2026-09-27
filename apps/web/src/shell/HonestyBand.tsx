// On every frame of a run (I8, I11): who is simulated, who may authorize, and
// which kind of model ran. `h` is honesty() of the full log where it is known.
import type { Honesty } from "../provenance";
import { Icon } from "../ui/Icon";
import { ProvenanceChip } from "./ProvenanceChip";
import "./HonestyBand.css";

export function HonestyBand({ h }: { h: Honesty }) {
  return (
    <div className="pl-band">
      {h.sim.length > 0 && (
        <p role="note" aria-label="Simulated parties" className="pl-band-sim">
          <Icon name="simulated" size="sm" />
          {h.sim.join(" · ")}
        </p>
      )}
      {h.principal && <p>{h.principal}</p>}
      {h.chip && <ProvenanceChip chip={h.chip} />}
    </div>
  );
}
