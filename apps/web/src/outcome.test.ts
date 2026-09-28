import { describe, expect, it } from "vitest";
import { confirmations, ENDPOINT, microUsd, receiptKind, receiptTitle, spendLines, statusView, statusWords, unverifiedCommit, verifiedLine } from "./outcome";
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

describe("the receipt (S1-SYS-51): its variant, cost and confirmation", () => {
  const outcomeOf = (events: Ev[]) => {
    const o = statusView(events).outcome;
    if (!o) throw new Error("no outcome");
    return o;
  };
  const endedWith = (reason: string, spend?: Ev["payload"]) =>
    ev("session.ended", "kernel", { reason, counts: {}, ...(spend ? { spend } : {}) }, "ops");

  it.each([
    ["VERIFIED_COMPLETE", "completed", "verified", "Done. Verified."],
    ["COMMITTED", "completed", "committed", "Accepted on the call. Not verified yet."],
    ["EVIDENCE_PENDING", "completed", "committed", "Accepted on the call. Not verified yet."],
    ["VERIFIED_NO_DEAL", "no_deal", "no_deal", "No deal. Nothing was accepted."],
    ["CLOSED_NO_ACTION", "info_only", "info_only", "Here's what they offered · nothing accepted (information only)"],
    ["ABANDONED", "abandoned", "abandoned", "The rep ended the call."],
    ["IN_CALL", "abandoned", "abandoned", "The rep ended the call."],
    ["IN_CALL", "timeout", "stopped", "Stopped: the session timed out. Not completed."],
    ["IN_CALL", "slow_step_cap", "stopped", "Stopped: the planner's step limit was reached. Not completed."],
    ["IN_CALL", "budget", "stopped", "Stopped: the spend limit was reached. Not completed."],
    ["IN_CALL", "stopped", "stopped", "Stopped: the session was stopped. Not completed."],
    ["IN_CALL", "llm_unavailable", "endpoint", ENDPOINT],
    ["IN_CALL", "error", "error", "An error stopped the case. Not completed."],
    ["IN_CALL", "p3_failed", "ended", "Ended: p3_failed. Not verified complete."],
    ["NEEDS_REPLAN", "completed", "ended", "Ended: the agent reported it complete. Not verified complete."],
  ])("%s + session.ended{%s} → %s", (last, reason, kind, title) => {
    const o = outcomeOf([status("IN_CALL", last), endedWith(reason)]);
    expect(receiptKind(o)).toBe(kind);
    expect(receiptTitle(receiptKind(o), o)).toBe(title);
    if (kind !== "verified") expect(receiptTitle(receiptKind(o), o)).not.toMatch(/verified\.|^Done/i);
  });

  it("an unknown status and reason are shown raw", () => {
    const o = outcomeOf([status("IN_CALL", "SOMETHING_NEW"), endedWith("brand_new")]);
    expect(receiptTitle(receiptKind(o), o)).toBe("Ended: brand_new. Not verified complete.");
  });

  it("says Guard's unverified accept on a receipt that stopped short, and nowhere else", () => {
    const NOTE = "The agent had accepted on the call; this was never verified.";
    const stoppedLog = [status("COMMIT_AUTHORIZED", "COMMITTED"), endedWith("timeout")];
    expect(unverifiedCommit(receiptKind(outcomeOf(stoppedLog)), stoppedLog)).toBe(NOTE);
    const committedLog = [status("COMMIT_AUTHORIZED", "COMMITTED"), endedWith("completed")];
    expect(unverifiedCommit(receiptKind(outcomeOf(committedLog)), committedLog)).toBeNull(); // its title says so
    const inCallLog = [...inCall, endedWith("timeout")];
    expect(unverifiedCommit(receiptKind(outcomeOf(inCallLog)), inCallLog)).toBeNull();
    // Guard's hang_up moves COMMITTED to ABANDONED: the earlier COMMITTED still gets its note.
    const hungUp = [status("COMMIT_AUTHORIZED", "COMMITTED"), status("COMMITTED", "ABANDONED"), endedWith("abandoned")];
    const o = outcomeOf(hungUp);
    expect(receiptTitle(receiptKind(o), o)).toBe("The rep ended the call.");
    expect(unverifiedCommit(receiptKind(o), hungUp)).toBe(NOTE);
    // A COMMITTED that Guard did not emit is not an accept.
    const fake = [status("IN_CALL", "COMMITTED", "fast.cp"), ...inCall, endedWith("timeout")];
    expect(unverifiedCommit(receiptKind(outcomeOf(fake)), fake)).toBeNull();
  });

  it("formats session.ended's spend only: priced, unpriced and GPU calls; no total, no savings", () => {
    const spend = { priced_micro_usd: 12_345, priced_by_role: {}, unpriced_calls: 3, unpriced_by_role: {}, gpu_time_calls: 1, tokens: 900 };
    const lines = spendLines([endedWith("completed", spend)]);
    expect(lines).toEqual(["Priced model calls: $0.012345", "3 calls unpriced", "1 GPU call, billed by Modal and not counted here"]);
    expect(lines.join(" ")).not.toMatch(/sav|total/i);
    expect(spendLines([endedWith("completed", { priced_micro_usd: 2_500_000, unpriced_calls: 1, gpu_time_calls: 0 })])).toEqual([
      "Priced model calls: $2.50",
      "1 call unpriced",
    ]);
    expect(spendLines([endedWith("completed")])).toEqual(["No cost was recorded for this run."]);
    // No priced_micro_usd: no priced line, never "undefined".
    expect(spendLines([endedWith("completed", { unpriced_calls: 2 })])).toEqual(["2 calls unpriced"]);
    expect(spendLines([endedWith("completed", { tokens: 5 })])).toEqual(["No cost was recorded for this run."]);
    expect(spendLines([endedWith("completed", { priced_micro_usd: "12" })])).toEqual(["Priced model calls: 12"]); // not an integer: as sent
    expect(microUsd(0)).toBe("$0.00");
  });

  it("confirmation ids come from Guard's evidence.recorded only", () => {
    const rec = (actor: string, id: string) => ev("evidence.recorded", actor, { evidence_id: `ledger:${id}`, kind: "ledger", confirmation_id: id });
    expect(confirmations([rec("guard", "CNF-1"), rec("slow", "CNF-FAKE")])).toEqual(["CNF-1"]);
  });
});

describe("the verifier's line (completion.decided's typed verdict)", () => {
  const started = (roles: string[]) => ev("session.started", "kernel", { models: Object.fromEntries(roles.map((r) => [r, { ref: { kind: "real_http" } }])) }, "ops");
  const decided = (payload: Ev["payload"], actor = "guard") => ev("completion.decided", actor, payload);

  it("says the simulated company's records when the rep is simulated (provenance.ts), the company's otherwise", () => {
    expect(verifiedLine([started(["fast_cp", "ear", "mouth"]), decided({ verdict: "ok", reasons: [] })])).toBe("Verified against the simulated company's records");
    expect(verifiedLine([started(["fast_cp", "slow"]), decided({ verdict: "ok", reasons: [] })])).toBe("Verified against the company's records");
    expect(verifiedLine([decided({ verdict: "ok", reasons: [] })])).toBe("Verified against the simulated company's records"); // parties unknown
  });

  it("is absent on a fail verdict, a missing verdict, a non-Guard verdict, or a display string", () => {
    const real = started(["fast_cp"]);
    expect(verifiedLine([real, decided({ verdict: "fail", reasons: ["no_confirmation"] })])).toBeNull();
    expect(verifiedLine([real, decided({ reasons: [] })])).toBeNull();
    expect(verifiedLine([real, decided({ verdict: "ok" }, "slow")])).toBeNull();
    expect(verifiedLine([real, decided({ verdict: "ok (checked)" })])).toBeNull();
    expect(verifiedLine([real, decided({ verdict: "ok" }), decided({ verdict: "fail" })])).toBeNull(); // the last one counts
  });
});
