// The phone's decision sheet (Sheet.tsx) sits between the case header and the composer dock (S1-SYS-92; it was CSS
// anchor(), which Firefox and older Safari lack, so they got a bottom sheet over the composer). The sheet is
// position: fixed, and its box comes from the two measured rects only: a top and a height, never a bottom, which a
// mobile browser's dynamic toolbar would shift (the fixed containing block is not clientHeight).

/** Where the sheet is placed: a phone whose page does not scroll (a short, landscape one keeps live.css's bottom sheet). */
export const PLACED = "(max-width: 767px) and (height > 500px)";

/** The sheet's inline top, bottom, height and max-height ("" leaves live.css's). */
export type Box = { top: string; bottom: string; height: string; maxHeight: string };

export const UNPLACED: Box = { top: "", bottom: "", height: "", maxHeight: "" };

/**
 * From the header's bottom to the dock's top, in whole px that never overlap either. Folded (`bar`: the bar's height),
 * only the bar shows: it sits on the dock.
 */
export function sheetBox(head: { bottom: number }, dock: { top: number }, bar: number | null): Box {
  if (bar !== null) return { ...UNPLACED, top: `${Math.max(0, Math.floor(dock.top - bar))}px`, bottom: "auto" };
  const top = Math.max(0, Math.ceil(head.bottom));
  return { top: `${top}px`, bottom: "auto", height: `${Math.max(0, Math.floor(dock.top) - top)}px`, maxHeight: "none" };
}
