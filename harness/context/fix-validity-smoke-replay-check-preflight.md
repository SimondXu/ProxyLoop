# Fix: `validity-smoke-check` re-derives labels from the stored raw outputs (P1 D2-2)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Branch `fix/validity-smoke-replay-check` from `main`.

## Defect (audit D2-2, `harness/code_review/repo-audit-D2.md:40-43`)

`scripts/run_phase_03a1_validity_smoke.py --check` (in `make test` as
`validity-smoke-check`) re-derives nothing label-bearing from the stored raw
model outputs of the r5 validity-smoke artifact. The audit's tamper probe:
flip the fee-trap row to valid, recompute the counts and `report_fingerprint`
with the script's own helpers → `_check_report(...)` returns `(True, ())`
with `end_to_end_valid_count: 6`. `ml/tests/test_validity_smoke.py:53-111`
bumps counts without editing rows. G2b (#48) fixed the same class of defect
for r4 only (`hosted_rescore.py`); r5 is still self-attested.

## Frozen design

Follow the G2b pattern (`ml/evaluation/src/proxyloop_evaluation/hosted_rescore.py`,
`harness/log/fix-hosted-evaluator-evolution.md`): committed hosted bytes are
provenance and are **never rewritten**; the check re-derives labels.

1. `--check` replays every r5 row's stored raw output through the **current**
   evaluator (the same replay entry points G2b uses — `replay_v2` /
   `replay_condition_v2` or the smoke-specific equivalent; find the path the
   r5 writer used) and compares the re-derived per-row labels
   (validity / completion / e2e / reason codes — whatever the r5 row schema
   carries) and aggregate counts against the committed artifact.
2. If the current evaluator re-derives exactly the committed labels, the
   check requires equality. If it differs (the G2c state-based verifier
   landed after r5), do **not** rewrite r5: record the difference as an
   explicit module-level constant of expected changed rows (as
   `_EXPECTED_ROWS_CHANGED_VS_R4` does), require the replay to match
   committed-except-those-rows exactly, and report the delta in the log.
   STOP and report to root before choosing this branch if more than a
   handful of rows move or the move changes a headline count.
3. Integrity checks the script already performs stay (fingerprints, counts).
4. Never touch frozen modules (`qwen_mlx.py`, `fast_output.py`,
   `fresh_fixtures.py`, `phase03b_experiment.py`, `hosted_rerun.py`,
   `openai_frontier.py`) or any committed artifact bytes. Add modules; do
   not edit frozen ones. No hosted/network call.

## Regression tests (write first)

In `ml/tests/test_validity_smoke.py` (or a sibling):
- **T1 (passes the old check, must fail the new one)**: the audit probe —
  copy the committed r5 artifact to a tmp dir, flip one invalid row's labels
  to valid, recompute counts and `report_fingerprint` with the script's
  helpers → the check reports a label/replay mismatch.
- **T2**: the committed artifact passes.
- **T3**: tampering a stored raw output (so replay yields a different label
  while committed labels are unchanged) is caught.

## Verification

The test module; `make validity-smoke-check`; `make hosted-rescore-check`
and `make phase03c-rescore-check` (must stay green); `make lint`,
`make typecheck`, `make preflight-fast`.
