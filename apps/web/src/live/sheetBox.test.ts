import { describe, expect, it } from "vitest";
import { PLACED, sheetBox, UNPLACED } from "./sheetBox";

describe("sheetBox: the phone's sheet between the case header and the composer (S1-SYS-92)", () => {
  it("runs from the header's bottom to the dock's top, in whole px that overlap neither", () => {
    expect(sheetBox({ bottom: 186.4 }, { top: 700.6 }, 844, false)).toEqual({ top: "187px", bottom: "144px", maxHeight: "none" });
    expect(sheetBox({ bottom: 120 }, { top: 740 }, 844, false)).toEqual({ top: "120px", bottom: "104px", maxHeight: "none" });
  });

  it("folded, keeps only the bottom: the bar sits on the dock with its own height", () => {
    expect(sheetBox({ bottom: 120 }, { top: 740 }, 844, true)).toEqual({ ...UNPLACED, bottom: "104px" });
  });

  it("never goes off screen", () => {
    expect(sheetBox({ bottom: -30 }, { top: 900 }, 844, false)).toEqual({ top: "0px", bottom: "0px", maxHeight: "none" });
  });

  it("is placed only on a phone whose page does not scroll (a short, landscape one keeps the bottom sheet)", () => {
    expect(PLACED).toBe("(max-width: 767px) and (min-height: 501px)");
    expect(UNPLACED).toEqual({ top: "", bottom: "", maxHeight: "" });
  });
});
