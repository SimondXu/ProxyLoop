import { describe, expect, it } from "vitest";
import { SIM_REP, SIM_USER, UNKNOWN_PARTIES } from "./conversation";
import { BASELINE, honesty, HUMAN_PRINCIPAL, LIVE, RECORDED, SCRIPTED } from "./provenance";
import type { Ev } from "./replay";

let seq = 0;
const ev = (type: string, actor: string, payload: Ev["payload"] = {}, t_ms = 0): Ev => {
  seq += 1;
  return { run_id: "r", seq, event_id: `r:${seq}`, t_ms, type, actor, stream: "ops", cause_ids: [], payload };
};
const started = (kinds: Record<string, string>, t_ms = 0, actor = "kernel") =>
  ev("session.started", actor, { models: Object.fromEntries(Object.entries(kinds).map(([r, kind]) => [r, { ref: { kind, model_id: `${r}-m` } }])) }, t_ms);
const LANES = { fast_user: "real_http", fast_cp: "real_http", slow: "real_http" };

describe("the honesty band labels", () => {
  it("names the simulated rep with conversation.ts's exact constant, and a human principal's authority", () => {
    const h = honesty([started({ ...LANES, ear: "real_http", mouth: "real_http" })]);
    expect(h.sim).toEqual([SIM_REP]);
    expect(SIM_REP).toBe("Simulated rep; no real company was called");
    expect(h.principal).toBe(HUMAN_PRINCIPAL);
    expect(HUMAN_PRINCIPAL).toBe("Only your clicks can authorize a deal");
  });

  it("adds the simulated user, and then no human principal authorizes anything", () => {
    const h = honesty([started({ ...LANES, ear: "real_http", simuser: "real_http" })]);
    expect(h.sim).toEqual([SIM_REP, SIM_USER]);
    expect(h.principal).toBeNull();
  });

  it("says the parties are not known yet without a kernel session.started (a forged one does not count)", () => {
    for (const events of [[], [started({ ...LANES, ear: "real_http" }, 0, "fast.user")]]) {
      const h = honesty(events);
      expect(h.sim).toEqual([UNKNOWN_PARTIES]);
      expect(UNKNOWN_PARTIES).toMatch(/^Parties not known yet/);
      expect([h.principal, h.chip]).toEqual([null, null]);
    }
  });

  it("a human rep and a human principal: no sim label, only the authority line", () => {
    expect(honesty([started(LANES)])).toMatchObject({ sim: [], principal: HUMAN_PRINCIPAL });
  });

  it("is read from the full log: at t=0 the time-filtered view has no session.started, the band still has the labels", () => {
    const full = [ev("chan.opened", "kernel", { lane: "user" }, 0), started({ ...LANES, ear: "test_fake" }, 500)];
    const atZero = full.filter((e) => e.t_ms <= 0);
    expect(honesty(atZero).sim).toEqual([UNKNOWN_PARTIES]); // why the replay must not pass its filtered view
    expect(honesty(full)).toMatchObject({ sim: [SIM_REP], chip: { label: SCRIPTED, scripted: true } });
  });
});

describe("the provenance chip", () => {
  it("all real_http → Live models", () => {
    expect(honesty([started(LANES)]).chip).toEqual({
      label: LIVE,
      scripted: false,
      roles: [
        { role: "fast_user", label: "Live model" },
        { role: "fast_cp", label: "Live model" },
        { role: "slow", label: "Live model" },
      ],
    });
  });

  it("any test_fake → the scripted label, over every other kind", () => {
    for (const other of ["real_http", "recorded_replay", "baseline", "grpc_magic"]) {
      const chip = honesty([started({ ...LANES, slow: other, fast_cp: "test_fake" })]).chip;
      expect([chip?.label, chip?.scripted]).toEqual([SCRIPTED, true]);
    }
    expect(SCRIPTED).toBe("Scripted test run · no models called");
  });

  it("any recorded_replay → Recorded replay", () => {
    expect(honesty([started({ ...LANES, fast_user: "recorded_replay" })]).chip?.label).toBe(RECORDED);
  });

  it("baseline is named per role in the details; the chip still says which models ran live", () => {
    const chip = honesty([started({ ...LANES, fast_cp: "baseline" })]).chip;
    expect(chip?.label).toBe(LIVE);
    expect(chip?.roles).toContainEqual({ role: "fast_cp", label: BASELINE });
    expect(BASELINE).toBe("Baseline (scripted policy)");
    expect(honesty([started({ fast_cp: "baseline" })]).chip?.label).toBe(BASELINE);
  });

  it("shows an unknown or missing kind raw, never as live", () => {
    const chip = honesty([started({ ...LANES, slow: "grpc_magic" }), ev("x", "kernel")]).chip;
    expect(chip?.label).toBe("Model kind: grpc_magic");
    expect(chip?.roles).toContainEqual({ role: "slow", label: "grpc_magic" });
    const bare = honesty([ev("session.started", "kernel", { models: { slow: {} } })]).chip;
    expect([bare?.label, bare?.roles]).toEqual(["Model kind: unknown", [{ role: "slow", label: "unknown" }]]);
  });
});
