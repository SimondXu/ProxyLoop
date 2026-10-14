# ADR-0031: An offer stays open for the call

- **Status:** accepted (the user, 2026-10-13: "选 A, NORTH_STAR 也按你说的改")
- **Date:** 2026-10-13
- **Task:** S1-SYS-111
- **Amends:** NORTH_STAR I7 (offer TTL); the four S1 families move to version 2

## Context
Every rung in the four S1 families had a hidden `ttl_s: 180`, and the rep's policy expired the offer silently once that time had passed (`env/counterparty/policy.py`). On the read-back, the same rep said "no expiry" (`expires: none` in `hidden`), and Slow's status bar never showed the clock. The agent therefore could not see the deadline, and the one thing it was told about the deadline was false.

Real retention reps do not behave this way:
- An offer is open while the call goes on.
- Any time pressure is stated, for example "only on this call" or "today only".
- A rep does not withdraw an offer three minutes in while the caller is still asking about its terms.

In the validation battery after ADR-0030 (`runs/v2-2862d54`), 3 of the 4 agent failures came from this clock:
- In 0a6cf0 and 08f079, the accept was released at about 150–170 s and voiced after the 180 s window. COMMITTED then had no exit, and the session timed out.
- In 247b62, the offer expired during a slow read-back.

The rule penalised the read-back that the design requires. It was not testing whether the agent dawdles.

## Decision
- **No time limit by default.** An offer's `ttl_s` is optional (`env/tasks/schema.py`). `None` means the offer is open for the whole call and ends only with the call or with a withdrawal the rep states. The four S1 families drop `ttl_s` and become version 2.
- **The timed path stays.** `ttl_s` with a number still expires the offer (`policy.py`). It is kept for a future family whose rep states a time window on the read-back. That family should state the window and show it to Slow, so the deadline is never hidden.
- **Old versions are archived.**
  - The version-1 family files are archived under `tasks/families/v1/`. `env/tasks/loader.resolve` loads an archived version when a `task_ref` names it, so the `evidence/s0` bundles (`cp-direct-discount@1`) still resolve to their instance hash.
  - The offer-lapse tests use the v1 ladder.
- **NORTH_STAR I7.** "Offer TTL" becomes "an offer stays open for the call and ends with the call or a withdrawal the rep states (no hidden clock)".

## Consequences
- **Not comparable with earlier runs.** Runs at version 2 are not pooled with the version-1 runs (M1, M2, M3, `runs/v2-2862d54`). `task_ref` carries the version. The next battery re-measures all four families.
- **Time pressure that remains:** rep patience (silence strikes, hold limit, identity strikes) and the session caps. A separate audit of these rules is in progress, and its changes go into the same pre-battery batch.
- **Still needed:** COMMITTED must have an exit, because a rep can still refuse an accept (a withdrawal or a dropped call). This is PLAN Now/Next 2.
- **Contract:** none (`contract/` is unchanged).
