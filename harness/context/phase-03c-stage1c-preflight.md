# Phase 03C Stage 1c Preflight — prompt v5/v6, targeted re-pilot, full generation

Date: 2026-09-21

## Activation evidence

- Continuation of the user's whole-flow authorization; the pilot in Stage 1b
  (PR #35, `5648ab4`) returned Go for `claude-sonnet-5`, which is the
  contract's precondition for full generation (≤ USD 150).
- Branch `feat/phase-03c-stage1c-full-generation`; `status.toml`
  `in_progress`, `active_product_phase = "03C-stage1c"`.

## Observed state (from the Stage 1b log)

- Pilot accepted rows covered 7 of 10 train families: fee-total-cost-trap
  (teacher comparison error, 59/60), forbidden-term (`needed`/`reason_code`
  convention gap, 60/60), disclosure-restriction (frozen detector flags the
  echoed field name, 59/60).
- Dedup removed 133/600 samples at k = 3 (temperature 0.7 repeats itself).
- Observed cost ≈ USD 0.0147 per Sonnet call; sequential sampling ≈ 9
  calls/min.

## Frozen decisions

1. Prompt **v5** = v4 with exactly three wording edits (rule 6: state both
   numbers and the comparison; rule 7: offer non-compliance is never a
   replan; never repeat a requested disclosure field name). v3/v4 bytes and
   their artifacts are untouched; the committed v4 pilot check reads the
   report's stored prompt version.
2. Targeted v5 re-pilot before spending: the three affected families plus
   two controls (direct-success, multi-hazard), 20 prompts each, k = 3,
   separate out-dir `teacher-v5-repilot`, charged to the Stage 1c budget.
   Result: F1 98%, F1∧F2 94%, F1–F4 91% → Go; fee-trap 1.00, forbidden-term
   1.00, disclosure 0.83, multi-hazard 1.00, direct-success 0.87; USD 4.50.
   Failure attribution (corrected from the first reading of the report):
   - direct-success 8/60 failures = 2 `dialogue_act` errors on one prompt
     + 6 `invalid_json` from `finish_reason=length` (11/60 v5 samples of
     this family were truncated at 512 output tokens vs 0/60 under v4: the
     v5 rule 6 "state both numbers" wording lengthens `response_text`);
   - disclosure-restriction 10/60 failures = 10 `dialogue_act` errors
     (`counter` where the target is `challenge`); one sample echoed
     `account_pin` but failed F2 first, so the F3/F4 detector never saw it
     (0 detector quarantines is an ordering artifact, not a clean bill).
   **v5 regression found in the full run** (the 57 successful samples of
   `teacher-full`, all `absent-evidence` / `retention-gated-v1`): v5 rule 7
   ("offer non-compliance is never a replan and never needs the reasoner")
   made the teacher skip rule 5 when a view has BOTH missing confirmation
   evidence and a non-compliant offer. v4 pilot: (`counter`, needed=true)
   27/30 on that configuration; v5: (`counter`, needed=false) 52/57. The
   family was not in the v5 re-pilot, so the Go did not cover it.
3. Prompt **v6** = v5 with exactly two edits: the header now says "Apply
   the first rule that matches and stop; rules 1-5 are Provider-state rules
   and take precedence over the offer checks in rules 6-7", and rule 7's
   trailing clause becomes "an offer that fails rule 6 is countered without
   the reasoner unless a Provider-state rule 1-5 already matched". v3/v4/v5
   bytes are frozen by tests; the manifest is rendered with v6; the v4 pilot
   and v5 re-pilot checks read their stored versions. **v6 re-pilot gate**
   before any full generation: absent-evidence, expired-approval,
   forged-evidence, fee-total-cost-trap, forbidden-term,
   disclosure-restriction, 20 prompts each, k = 3 (360 calls; the v6
   dry run prints USD 5.73 worst case, ≈ USD 5.3 expected), separate
   out-dir; the pilot decision must be Go on **every**
   family's per-family F2 (not only the overall rule) before the full run.
   Full generation afterwards keeps the frozen shape: all 4,000 train rows,
   `claude-sonnet-5`, k = 2, concurrency 6, `usd_ceiling` 140 (script
   default) so re-pilots + full run ≤ USD 150 accounted. Dev rows (seeds
   900..909) are never sampled. Out-dir `teacher-full`; raw and accepted
   JSONL git-ignored, manifest / quarantine / quality / generation report
   committed; the report carries `prompts_complete`, `run_complete`,
   `stop_reason`, and no Go/Stop decision.
4. Acceptance per contract: ≥ 2,500 accepted rows, zero cross-split
   families, zero forbidden model-input keys, ledger ≤ cap;
   `training_ready` is computed, never hand-set. Family coverage is
   reported; a family with < 50 accepted rows is a finding for Stage 2.
5. No training in this stage.

## Relay outage in the first full run (2026-09-21)

- The run was not interrupted by hand: it consumed all 8,000 calls (57
  succeeded, 7,942 `AuthenticationError` 401, 1 `PermissionDeniedError`
  403) in a roughly two-minute 401 storm after the relay quota ran out. The
  ledger charged every failed call at the pre-call worst case and reports
  USD 125.84 against the 140 ceiling; real spend is the 57 successes
  (≈ USD 0.95 at the placeholder rates).
- Fixes applied: `sample_teacher` now has a circuit breaker (a 401/403 or
  five consecutive failed calls sets the shared stop flag; `stop_reason`
  is written to the ledger and the generation/pilot report; prompts never
  started are never reserved or charged), and both scripts have
  `--reset-failed-charges`.
- Ledger reset procedure (deliberate, before any rerun in the same
  out-dir): `uv run --project ml python -m scripts.run_phase03c_teacher_generation
  --reset-failed-charges --out-dir <dir> --usd-ceiling 140` rebuilds
  `phase-03c-cost-ledger.json` from the raw samples JSONL (succeeded calls
  keep their recorded estimate, failed calls count at zero), prints the
  totals before and after, and writes nothing else; then rerun without
  flags to resume. The `teacher-full` ledger has **not** been reset yet:
  that is a root decision, and the v5 samples in that directory are in any
  case superseded by v6.

## TODO before the v6 re-pilot

- Verify v6 token fit on the MLX smoke (`scripts/run_phase03c_smoke.py
  --prompt-version v6 --verify-token-fit`): the v6 block is 177
  characters longer than v5; the rendered prompt must stay under
  `PROMPT_TOKEN_LIMIT` (2048) on every development example.

## v6 re-pilot and full-run decision (2026-09-22, after the relay key was topped up)

- v6 targeted re-pilot (6 families × 20 prompts × k = 3 = 360 calls,
  USD 5.43, `teacher-v6-repilot/`): F1 97.5%, F1∧F2 87.8%, F1–F4 87.2%
  → Go. Per family F2: absent-evidence 0.95 (v5 regression fixed),
  expired-approval 1.00, fee-total-cost-trap 1.00, forbidden-term 1.00,
  forged-evidence 0.78, disclosure-restriction 0.53.
- Disclosure is a **v5→v6 regression**, not merely a coverage gap: position-2
  `challenge` went v4 30/30 → v5 20/30 → v6 6/30 (position 1: 30 → 26). The
  teacher applies rule 5 (evidence unavailable) before rule 2 despite the v6
  precedence sentence. Under the contract's aggregate Go rule it does not
  block full generation, but Stage 2 must treat disclosure-restriction as
  skewed toward position 1 (position-2 accepted rows will be few) and the
  Stage 3 family breakdown must report it separately.
- Full generation launched with v6 in a fresh out-dir `teacher-full-v6`
  (k = 2, concurrency 6, ceiling USD 140; the v5 `teacher-full/` report is
  kept as evidence of the quota outage and is not resumed because its
  samples carry v5 prompt fingerprints).
- Stage 1c accounted spend so far: v5 re-pilot 4.50 + v6 re-pilot 5.43 +
  the v5 full-run's 57 successful calls ≈ 0.95 (its ledger shows 125.84
  because of worst-case charging of the 401 storm).
