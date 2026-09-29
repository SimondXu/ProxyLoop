import { describe, expect, it } from "vitest";
import { PLACED, sheetBox, UNPLACED } from "./sheetBox";

describe("sheetBox: the phone's sheet between the case header and the composer (S1-SYS-92)", () => {
  it("runs from the header's bottom to the dock's top, in whole px that overlap neither", () => {
    expect(sheetBox({ bottom: 186.4 }, { top: 700.6 }, null)).toEqual({ top: "187px", bottom: "auto", height: "513px", maxHeight: "none" });
    expect(sheetBox({ bottom: 120 }, { top: 740 }, null)).toEqual({ top: "120px", bottom: "auto", height: "620px", maxHeight: "none" });
  });

  it("uses only the two rects: no viewport height, so a mobile toolbar cannot shift it", () => {
    expect(sheetBox.length).toBe(3);
    expect(sheetBox({ bottom: 120 }, { top: 740 }, null).bottom).toBe("auto");
  });

  it("folded, sits the bar on the dock with the bar's own height", () => {
    expect(sheetBox({ bottom: 120 }, { top: 740.5 }, 56)).toEqual({ ...UNPLACED, top: "684px", bottom: "auto" });
  });

  it("never goes off screen or negative", () => {
    expect(sheetBox({ bottom: -30 }, { top: -10 }, null)).toEqual({ top: "0px", bottom: "auto", height: "0px", maxHeight: "none" });
  });

  it("is placed only on a phone whose page does not scroll (a short, landscape one keeps the bottom sheet)", () => {
    expect(PLACED).toBe("(max-width: 767px) and (height > 500px)");
    expect(UNPLACED).toEqual({ top: "", bottom: "", height: "", maxHeight: "" });
  });
});
