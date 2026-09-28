// A phone's open approval card (redesign §3.6): a non-modal bottom sheet over every tab,
// folded to a bar and back only by the reader's click. No focus trap, no timer, and a new
// card never takes focus. Above 760px the bar is hidden and the card sits in the chat.
import { useState, type ReactNode } from "react";

export function Sheet({ bar, children }: { bar: string; children: ReactNode }) {
  const [folded, setFolded] = useState(false);
  return (
    <div className={`pl-sheet${folded ? " pl-sheet-folded" : ""}`}>
      <button type="button" className="pl-sheet-bar" aria-expanded={!folded} onClick={() => setFolded(!folded)}>
        {folded ? bar : "Hide the decision"}
      </button>
      <div className="pl-sheet-body">{children}</div>
    </div>
  );
}
