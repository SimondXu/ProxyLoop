import { describe, expect, it } from "vitest";
import { statusView, statusWords } from "./outcome";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, stream: Ev["stream"] = "agent"): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms: seq, type, actor, stream, cause_ids: [], payload };
};
const status = (previous: string, to: string, actor = "guard") => ev("status.changed", actor, { previous, status: to });
const ended = (reason: string) => ev("session.ended", "kernel", { reason, counts: {} }, "ops");
const inCall = [status("INTAKE", "IN_CALL")];

describe("the status line (guard's status.changed)", () => {
  it("maps each status to plain words; COMMITTED is accepted, not yet verified", () => {
    expect(statusView([]).line).toBe("Status: starting (no status yet)");
    expect(statusView(inCall).line).toBe("Status: on the call");
    expect(statusView([...inCall, status("IN_CALL", "AWAITING_APPROVAL")]).line).toBe("Status: waiting for your approval");
    expect(statusView([status("COMMIT_AUTHORIZED", "COMMITTED")]).line).toBe("Status: accepted on the call, not yet verified");
  });

  it("renders an unknown status raw, never hidden", () => {
    expect(statusWords("SOMETHING_NEW")).toBe("SOMETHING_NEW");
    expect(statusView([status("IN_CALL", "SOMETHING_NEW")]).line).toBe("Status: SOMETHING_NEW");
  });

  it("ignores a status.changed that Guard did not emit", () => {
    expect(statusView([...inCall, status("IN_CALL", "VERIFIED_COMPLETE", "fast.user")]).line).toBe("Status: on the call");
  });

  it("says the session ended, with its reason, instead of a stale IN_CALL", () => {
    const v = statusView([...inCall, ended("abandoned")]);
    expect(v.line).toBe("Session ended: the rep hung up");
    expect(v.line).not.toMatch(/on the call|IN_CALL/);
    expect(v.outcome).toMatchObject({ reason: "abandoned", status: "IN_CALL", verified: false });
  });
});

describe("the outcome banner (session.ended + the last status and completion.decided)", () => {
  it("has no banner before session.ended, even on VERIFIED_COMPLETE", () => {
    expect(statusView([status("EVIDENCE_PENDING", "VERIFIED_COMPLETE")]).outcome).toBeNull();
  });

  it("says Verified complete only on VERIFIED_COMPLETE", () => {
    const v = statusView([
      status("EVIDENCE_PENDING", "VERIFIED_COMPLETE"),
      ev("completion.decided", "guard", { verdict: "ok", reasons: [] }),
      ended("completed"),
    ]);
    expect(v.outcome).toEqual({ title: "Verified complete", verified: true, reason: "completed", status: "VERIFIED_COMPLETE", verdict: "ok" });
  });

  it.each([
    ["timeout", "IN_CALL", "Ended: the session timed out. Not verified complete."],
    ["abandoned", "ABANDONED", "Ended: the rep hung up. Not verified complete."],
    ["stopped", "COMMITTED", "Ended: stopped. Not verified complete."],
    ["no_deal", "IN_CALL", "Ended: no deal was made. Not verified complete."],
    ["info_only", "CLOSED_NO_ACTION", "Ended: information only, no action taken. Not verified complete."],
    ["escalate", "ESCALATED", "Ended: escalated to a person. Not verified complete."],
    ["llm_unavailable", "IN_CALL", "Ended: a model endpoint was unavailable. Not verified complete."],
    ["completed", "COMMITTED", "Ended: the agent reported it complete. Not verified complete."],
    ["completed", "NEEDS_REPLAN", "Ended: the agent reported it complete. Not verified complete."],
    ["slow_step_cap", "IN_CALL", "Ended: slow_step_cap. Not verified complete."],
  ])("session.ended{%s} at %s never implies success", (reason, last, title) => {
    const v = statusView([status("IN_CALL", last), ended(reason)]);
    expect(v.outcome).toMatchObject({ title, verified: false, reason, status: last });
    expect(v.outcome?.title).not.toMatch(/^Verified/);
  });

  it("names a verified no-deal as verified, and a failed verifier's reasons", () => {
    expect(statusView([status("IN_CALL", "VERIFIED_NO_DEAL"), ended("no_deal")]).outcome).toMatchObject({
      title: "Verified: no deal was made",
      verified: false,
    });
    const failed = statusView([
      status("EVIDENCE_PENDING", "NEEDS_REPLAN"),
      ev("completion.decided", "guard", { verdict: "fail", reasons: ["no_confirmation"] }),
      ev("completion.decided", "slow", { verdict: "ok", reasons: [] }),
      ended("completed"),
    ]);
    expect(failed.outcome).toMatchObject({ verified: false, verdict: "fail (no_confirmation)" });
  });

  it("reads session.ended from the kernel only", () => {
    expect(statusView([...inCall, ev("session.ended", "slow", { reason: "completed" }, "ops")]).outcome).toBeNull();
  });
});
