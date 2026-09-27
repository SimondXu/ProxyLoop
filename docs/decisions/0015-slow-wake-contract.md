# ADR-0015: Slow wake contract

- **Status:** accepted (root decisions under PLAN §0.5a, 2026-09-27, adopting the principal-architect wake and durability review, then revised the same day: the W1 rate limit (option B), `MAX_STEPS` 120 and the provisional runaway projection; the rep-text counterfactual (L5) is dropped after the user's I5 decision, ADR-0016)
- **Date:** 2026-09-27
- **Task:** S1-ROOT-08 (records); S1-SYS-29 builds it
- **Amends:** ARCHITECTURE §11 (Slow's wake list). Supersedes #162's HOLD re-relay (S1-SYS-26 bug 2, removed from #162 before merge).

## Context
- Slow is edge-triggered: it wakes on a new relay or on its own `wait` timer. It has to answer level conditions, though: the rep keeps waiting, FastC keeps holding. A repeated cp HOLD is deduplicated (`kernel/lanes.py` `_relay`), a rep `utt.final` triggers only FastC, and a Slow step that calls no tool schedules nothing. The two agents can deadlock while the process is alive and the log is complete.
- Observed in the main checkout's git-ignored runs: `runs/20260927T054451Z-655087` (abandoned in IDENTIFY), `runs/20260927T055218Z-f3a106` and `runs/20260927T060019Z-ed5063` (timeouts, with long stretches of rep turns that no Slow step saw), `runs/20260927T065319Z-8f7e69` (abandoned in IDENTIFY). Source: the plan-v3 handoff `2026-09-27-wake-and-durability.md`.
- Options:
  - re-relay a repeated HOLD (#162, rounds 2–3). Rejected: the stateful rule grew a condition in every round;
  - Temporal as the always-on driver. Rejected for now: it fixes neither the deduplicated HOLD, nor the silent `content_filter` step (retrying that would be a retry on model output, rule 12), nor stale guidance (#165);
  - a level-triggered wake contract in the kernel. Chosen.

## Decision
- **W1, the must-see set.** Slow wakes on `f2s.msg`, `user.msg` (through the fence), `chan.closed`, `approval.decided`, `mandate.decided`, `action.denied{approval.post}`, `speak.revoked` and `NEEDS_REPLAN`. Two wakes are new: the cp partner's `utt.final` while the call is open, and `chan.strike`. `chan.opened{cp}` opens the heartbeat window but is not a wake; the `call_opened` wake stays with ADR-0012 (S1-SYS-21). Today "in call" starts at session start, because `_open` emits `chan.opened{cp}`.
- **W1 rate limit (option B).** A rep turn does not wake Slow while FastC's generation for that same rep line is pending; when that generation ends, Slow wakes once, coalesced. The expected load is about one Slow step per rep turn [E], and Slow's attention lags by at most one FastC generation.
- **L1 liveness.** Every rep `utt.final` is seen by a Slow step whose basis is at or after its seq. That step starts once the running step and FastC's generation for that line have ended (the rate limit above).
- **L2 heartbeat.** While the cp call is open, the kernel wakes Slow `HEARTBEAT_S` = 15 s after any in-call step that did not end with a successful `wait`. A `wait(s)` can only make the next step come sooner. There is no heartbeat outside a call: the fence, `INTAKE_S` and `REDIAL_WAIT_S` cover those states.
- **L3 bounded.** One step runs at a time, and wakes that arrive during a step coalesce into the next. `MAX_STEPS` goes from 40 to 120 [E: about one step per rep turn, plus heartbeats, over a two-call 720 s session]; reaching it ends the session with `Abort("slow_step_cap")`.
- **L4 schedule independent of model output.** Apart from `wait` and `finish`, the wake schedule is a function of external events and the clock only. A normal step, a no-tool step, a refused step and a `content_filter` step give the same schedule (a property test). Rule-12 reading (root decision): a uniform heartbeat is not a retry on model output, because it fires on the clock whatever the model said, never because of what it said.
- **L5 fixed wake reasons.** Wake reasons are fixed strings from a closed set; no rep text travels through a wake. The rep-text counterfactual first planned here is dropped: under ADR-0016 Slow reads the rep's lines by design.
- **Module.** `kernel/wake.py` (new) is a bus subscriber, like `Authority`, and holds the kernel's only Slow timer; `kernel/session.py` loses `wake_slow`/`_timer` and grows by no net lines. `slow.step.started` may carry `cause_ids`. Slow's prompt gains one sentence on rep-turn and heartbeat wakes (S1-SYS-34 rewrites it for transcripts).
- **Runaway guard.** The S0 projection (300k tokens, 150 calls) would end smoke #2/#3 sessions as `budget`. S1-SYS-29 sets a provisional `PROJECTED` = (900k tokens, 400 calls) until the root re-derives both from smoke #2 bundles and measured TeamRouter prices. The $2 per-session cap stays; Luna is priced under it.
- **Durability constraints (zero cost now, for S5b).** Every wake source is enumerable, so it maps to a signal or a timer; every kernel timer's due time is derivable from the log plus constants; `session.ended{deferred}` carries the recovery information. They go into the S1-SYS-29 and S1-SYS-24 packets. Temporal is not the always-on driver now; the S5b design (ARCHITECTURE §15) waits for the user's timing decision.

## Evidence
None measured; this ADR records decisions. The failure traces are the four runs above. Smoke #2 (S1-ROOT-06) measures the diagnostic `slow_attention_lag` (EVAL §7).

## Consequences
- **Contract / fingerprint impact:** none. No event type, state field or `SessionConfig` field; `pl_user_v1` and `pl_cp_v2` are unchanged.
- **Data invalidated:** none.
- **Migration:** #162 merged without its HOLD re-relay. #164's partner-turn wake becomes a W1 case; #156's fence is unchanged; ADR-0012 is orthogonal; ADR-0014's defer stays Guard-issued (`HEARTBEAT_S` is shorter than the rep's hold clock). S1-SYS-29 merges before S1-CON-08, S1-SYS-21 and S1-SYS-05 (shared `kernel/session.py`, `slow/`).
- **Risks and what would make us revisit this.** More steps and spend per session (watch the step and budget caps). Slow over-guiding on empty rep turns (guides per rep turn, `superseded_lines`, the share of wait-only steps). TeamRouter latency. A heartbeat can mask a lost edge: count wakes by reason, and treat a heartbeat-woken step that changes state as a missed edge. A dispute over "heartbeat = retry" is settled by the L4 test.
