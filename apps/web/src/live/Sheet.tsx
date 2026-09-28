// A phone's open approval card (redesign §3.6): a non-modal bottom sheet above the composer,
// folded to a bar and back only by the reader's click. No focus trap, no timer, and a new
// card never takes focus. From 768px the bar is hidden and the card sits in the stream.
// The phone hides the band's authority line, so a human principal's (I6) sits here, where
// the click happens; never for a simulated principal (`human`: honesty().principal is set).
import { useState, type ReactNode } from "react";
import { HUMAN_PRINCIPAL, HUMAN_PRINCIPAL_SHORT } from "../provenance";

export function Sheet({ bar, human, children }: { bar: string; human: boolean; children: ReactNode }) {
  const [folded, setFolded] = useState(false);
  return (
    <div className={`pl-sheet${folded ? " pl-sheet-folded" : ""}`}>
      <button type="button" className="pl-sheet-bar" aria-expanded={!folded} onClick={() => setFolded(!folded)}>
        <span>{folded ? bar : "Hide the decision"}</span>
        {folded && human && <span className="pl-sheet-promise">{HUMAN_PRINCIPAL_SHORT}</span>}
      </button>
      <div className="pl-sheet-body">
        {children}
        {human && <p className="pl-sheet-promise">{HUMAN_PRINCIPAL}</p>}
      </div>
    </div>
  );
}
