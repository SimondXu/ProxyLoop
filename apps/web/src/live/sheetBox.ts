// The phone's decision sheet (Sheet.tsx) sits between the case header and the composer dock (S1-SYS-92; it was CSS
// anchor(), which Firefox and older Safari lack, so they got a bottom sheet over the composer). The sheet is
// position: fixed, so its box is in viewport px, measured from the two boxes.

/** Where the sheet is placed: a phone whose page does not scroll (a short, landscape one keeps live.css's bottom sheet). */
export const PLACED = "(max-width: 767px) and (min-height: 501px)";

/** The sheet's inline top, bottom and max-height ("" leaves live.css's). */
export type Box = { top: string; bottom: string; maxHeight: string };

export const UNPLACED: Box = { top: "", bottom: "", maxHeight: "" };

/**
 * From the header's bottom to the dock's top, in whole px that never overlap either (`viewport`: the layout viewport's
 * height). Folded, only the bar shows: it sits on the dock and keeps its own height.
 */
export function sheetBox(head: { bottom: number }, dock: { top: number }, viewport: number, folded: boolean): Box {
  const bottom = `${Math.max(0, Math.ceil(viewport - dock.top))}px`;
  if (folded) return { ...UNPLACED, bottom };
  return { top: `${Math.max(0, Math.ceil(head.bottom))}px`, bottom, maxHeight: "none" };
}
