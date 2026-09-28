// S1-SYS-69 drift guard: the timeline marks "Replaced by a newer instruction
// before it was spoken" on exactly the cp GUIDEs heard.fates supersedes. The
// synthetic fixture and its golden are shared with tests/web/test_superseded.py,
// which pins the golden against the Python rule; read here by path (node:fs,
// as replay.test.ts reads the replay fixture), so no Vite server.fs is involved.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as C from "./copy";
import { parseJsonl, type Ev } from "./replay";
import { timeline } from "./timeline";

const dir = (name: string) => fileURLToPath(new URL(`../../../tests/web/superseded/${name}`, import.meta.url));
const events = parseJsonl<Ev>(readFileSync(dir("events.jsonl"), "utf-8"));
const golden = JSON.parse(readFileSync(dir("golden.json"), "utf-8")) as string[];
const msgAt = new Map(events.filter((e) => e.type === "s2f.msg").map((e) => [String(e.seq), String(e.payload.msg_id)]));

describe("superseded GUIDEs: the timeline agrees with heard.fates", () => {
  const steps = timeline(events);

  it("marks exactly the golden set as replaced, and nothing else", () => {
    const replaced = steps.filter((s) => s.mark === C.REPLACED).map((s) => msgAt.get(s.key));
    expect(replaced.sort()).toEqual([...golden].sort());
    expect(golden.length).toBeGreaterThan(0);
  });

  it("keeps every other planner message's mark", () => {
    expect(steps.map((s) => [msgAt.get(s.key), s.mark])).toEqual([
      ["s2f-g1", C.REPLACED],
      ["s2f-g2", "✓ Said on the call"],
      ["s2f-g3", C.PASSED],
      ["s2f-g4", C.PASSED],
      ["s2f-g5", "Cut off before it was said"],
      ["s2f-e1", C.REPLACED],
      ["s2f-l1", C.REPLACED],
      ["s2f-g6", C.PASSED],
      ["s2f-g7", C.REPLACED],
      ["s2f-u1", C.PASSED],
      ["s2f-u2", C.PASSED],
      ["s2f-g8", C.PASSED],
    ]);
  });
});
