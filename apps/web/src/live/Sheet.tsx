// A phone's open approval card (redesign §3.6): a non-modal bottom sheet above the composer,
// folded to a bar and back only by the reader's click. No focus trap, no timer, and a new
// card never takes focus. From 768px the bar is hidden and the card sits in the stream.
// The phone hides the band's authority line, so a human principal's (I6) sits here: read
// before the card, shown under its click; never for a simulated principal (honesty().principal).
// Placed between the case header and the composer by measuring them (sheetBox.ts, S1-SYS-92).
import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { HUMAN_PRINCIPAL, HUMAN_PRINCIPAL_SHORT } from "../provenance";
import { PLACED, sheetBox, UNPLACED } from "./sheetBox";

export function Sheet({ bar, human, children }: { bar: string; human: boolean; children: ReactNode }) {
  const [folded, setFolded] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  usePlace(ref, folded);
  return (
    <div ref={ref} className={`pl-sheet${folded ? " pl-sheet-folded" : ""}`}>
      <button type="button" className="pl-sheet-bar" aria-expanded={!folded} onClick={() => setFolded(!folded)}>
        <span>{folded ? bar : "Hide the decision"}</span>
        {folded && human && <span className="pl-sheet-promise">{HUMAN_PRINCIPAL_SHORT}</span>}
      </button>
      <div className="pl-sheet-body">
        {human && <p className="pl-sheet-promise">{HUMAN_PRINCIPAL}</p>}
        <div className="pl-sheet-scroll">{children}</div>
      </div>
    </div>
  );
}

/**
 * Sets the sheet's inline box from its case's header and dock (sheetBox.ts): every frame while it is open, since the
 * header can move without anything resizing; folded, when either (or the case) changes size, the window resizes or
 * scrolls. Outside PLACED it clears them.
 */
function usePlace(ref: RefObject<HTMLDivElement | null>, folded: boolean) {
  useLayoutEffect(() => {
    const el = ref.current;
    const box = el?.closest(".pl-case");
    const head = box?.querySelector(".pl-casehead");
    const dock = box?.querySelector(".pl-dock");
    const bar = el?.querySelector(".pl-sheet-bar");
    if (!el || !box || !head || !dock || !bar) return;
    const mq = matchMedia(PLACED);
    let last = "";
    const place = () => {
      const b = mq.matches ? sheetBox(head.getBoundingClientRect(), dock.getBoundingClientRect(), folded ? bar.getBoundingClientRect().height : null) : UNPLACED;
      const key = Object.values(b).join();
      if (key !== last) Object.assign(el.style, b);
      last = key;
    };
    place();
    let frame = 0;
    const follow = () => {
      place();
      frame = requestAnimationFrame(follow);
    };
    if (!folded) frame = requestAnimationFrame(follow);
    const seen = new ResizeObserver(place);
    for (const x of [box, head, dock]) seen.observe(x);
    mq.addEventListener("change", place);
    addEventListener("resize", place);
    addEventListener("scroll", place, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      seen.disconnect();
      mq.removeEventListener("change", place);
      removeEventListener("resize", place);
      removeEventListener("scroll", place);
    };
  }, [ref, folded]);
}
