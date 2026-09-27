import { describe, expect, it } from "vitest";
import { phase } from "./phase";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, stream: Ev["stream"] = "agent"): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream, cause_ids: [], payload };
};
const status = (s: string, actor = "guard") => ev("status.changed", actor, { previous: "INTAKE", status: s });
const ended = (reason = "completed") => ev("session.ended", "kernel", { reason }, "ops");
const current = (events: Ev[]) => phase(events).steps.find((s) => s.state === "current")?.label;
const states = (events: Ev[]) => phase(events).steps.map((s) => `${s.label}: ${s.state}`);

// Every contract/state.py CaseStatus, and the step the stepper makes current (redesign §3.0).
const TABLE: [status: string, step: string, note: string | null][] = [
  ["INTAKE", "Details", null],
  ["MANDATED", "Limits", null],
  ["IN_CALL", "On the call", null],
  ["NEEDS_REPLAN", "On the call", null],
  ["AWAITING_APPROVAL", "Your decision", null],
  ["COMMIT_AUTHORIZED", "Result", null],
  ["COMMITTED", "Result", null],
  ["EVIDENCE_PENDING", "Result", "verifying…"],
  ["VERIFIED_COMPLETE", "Result", null],
  ["VERIFIED_NO_DEAL", "Result", null],
  ["ESCALATED", "Result", null],
  ["ABANDONED", "Result", null],
  ["CLOSED_NO_ACTION", "Result", null],
];

describe("the phase stepper (guard status.changed and kernel session.ended only)", () => {
  it.each(TABLE)("%s makes %s current", (s, step, note) => {
    const p = phase([status(s)]);
    expect(current([status(s)])).toBe(step);
    expect(p.note).toBe(note);
    expect(p.raw).toBeNull();
  });

  it("starts at Details before any status", () => {
    expect(states([])).toEqual(["Details: current", "Limits: todo", "On the call: todo", "Your decision: todo", "Result: todo"]);
  });

  it("marks a step passed without its status skipped, and one seen done", () => {
    expect(states([status("IN_CALL")])).toEqual(["Details: done", "Limits: skipped", "On the call: current", "Your decision: todo", "Result: todo"]);
    expect(states([status("MANDATED"), status("IN_CALL"), status("AWAITING_APPROVAL"), status("COMMITTED")])).toEqual([
      "Details: done",
      "Limits: done",
      "On the call: done",
      "Your decision: done",
      "Result: current",
    ]);
  });

  it("follows the latest status, also back from a decision to the call", () => {
    expect(current([status("IN_CALL"), status("AWAITING_APPROVAL"), status("IN_CALL")])).toBe("On the call");
  });

  it("makes Result current on session.ended, whatever the last status", () => {
    expect(states([status("IN_CALL"), ended("abandoned")])).toEqual([
      "Details: done",
      "Limits: skipped",
      "On the call: done",
      "Your decision: skipped",
      "Result: current",
    ]);
    expect(current([ended("llm_unavailable")])).toBe("Result");
  });

  it("shows an unknown status raw and keeps the last known step", () => {
    const p = phase([status("IN_CALL"), status("SOMETHING_NEW")]);
    expect(p.raw).toBe("SOMETHING_NEW");
    expect(current([status("IN_CALL"), status("SOMETHING_NEW")])).toBe("On the call");
  });

  it("ignores a status.changed not from guard and a session.ended not from the kernel", () => {
    expect(current([status("IN_CALL"), status("VERIFIED_COMPLETE", "fast.user")])).toBe("On the call");
    expect(current([status("IN_CALL"), { ...ended(), actor: "slow" }])).toBe("On the call");
  });
});
