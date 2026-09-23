# Fix log: `validity-smoke-check` re-derives r5 labels from raw outputs (D2-2)

Spec: `harness/context/fix-validity-smoke-replay-check-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md`. Branch
`fix/validity-smoke-replay-check`, rebased onto `main` @ `308ceed`. Closes the r5
half of audit D2-2 (`harness/code_review/repo-audit-D2.md:40-43`); G2b (#48)
closed the r4 half.

## What changed

- New `ml/evaluation/src/proxyloop_evaluation/validity_smoke_replay.py`:
  `replay_validity_smoke_summary` re-runs the r5 condition through the
  **current** `run_frontier_condition_v2` with the same adapters the r5
  writer used (`ValiditySmokeFrontierAdapter` medium, call cap 6, the
  writer's cost ceiling; `ValiditySmokeQwenAdapter`) and the prepared
  public-provider-state fixtures. The adapters are fed only r5's stored
  Slow/Fast raw outputs and hosted call evidence through four private
  `replay_v2` helpers (`_ReplayCompletions`, `_hosted_items`,
  `_qwen_generator`, `_selected_fixtures`) — imported, never edited, because
  `replay_v2.py` is frozen r4 execution bytes (`_R4_EXECUTION_PATHS`; the
  G2b precedent). Only row `latency_ms` and `hosted_calls[*].latency_ms`
  are copied from r5 (wall clock; an honest replay differs from r5 in
  exactly these fields and nothing else); the summary is rebuilt with
  `EvaluationSummaryV2.from_episodes`, so `latency_p50_ms` /
  `latency_p90_ms` are recomputed from them by the same formula.
  `check_validity_smoke_replay` then requires every other row field (labels,
  failure codes, routes, raw outputs, excerpt, tokens, cost, fingerprints,
  hosted call evidence) and every summary field to equal the replay.
- `scripts/run_phase_03a1_validity_smoke.py`: `_check_report` calls the
  replay check once the summary validates. All existing integrity checks
  (fingerprints, counts, provenance, r4 binding) stay.
- `ml/tests/test_validity_smoke.py`: T1 (audit probe: fee-trap row flipped
  to valid, counts / failure slices / smoke metrics / fingerprint recomputed
  with the script's own helpers), T2 (replay of the committed summary is
  `()`), T3 (a stored Fast raw output broken while labels stay committed).
  Review additions: a parametrised replay-tamper test (fee-trap
  `hosted_calls[0].status = "failed_provider_call"`; Slow `next_capability`
  changed to a schema-valid `decline`; `output_fingerprint` zeroed — the
  last would have passed with the earlier wholesale evidence preservation)
  and a non-JSON `slow_raw_output` test.
  The existing refingerprinted-tamper tests that bump counts without
  editing rows are kept unchanged: they still exercise the
  self-consistency checks, which remain part of the gate.
- `_check_report` reports `smoke metrics cannot be derived: …` instead of
  raising when a stored Slow output is not JSON (or not an object).
- No expected-delta constant: the current evaluator re-derives r5 exactly,
  so spec §2's equality branch applies.

## Evidence

- Red: before the change, T1 failed with `assert not True` — the current
  check accepted the probe artifact with `end_to_end_valid_count == 6`.
- Replay delta vs committed r5: **0 rows** changed and every summary field
  equal, latency percentiles included (15070/17097 ms, recomputed from the
  carried row latencies). Headline counts unchanged (e2e 5/6).
- T1 after the change: `_check_report` returns six replay failures (the
  fee-trap row, `provider_outcome_valid_count`, `end_to_end_valid_count`,
  `reference_match_count`, `false_completion_count`, `failure_slices`).
- T3: the add-on-removal row plus `fast_json/schema/canonical_valid_count`,
  `end_to_end_valid_count`, `failure_slices` flagged; prompt provenance is
  not disturbed by the edit, so only the replay catches it.
- No committed artifact or frozen module edited (`git diff --stat`: only
  the script and the test module; one new source module).

## Review

- Independent review (`reviewer`): **Approve** with five minors, all
  applied: (1) latency percentiles recomputed and compared, no excluded
  summary fields; (2) only `latency_ms` and `hosted_calls[*].latency_ms`
  carried from r5 instead of `_preserve_source_evidence`; (3) parametrised
  hosted-call-status / Slow-capability / output-fingerprint tamper tests;
  (4) non-JSON `slow_raw_output` returns a failure reason; (5) module
  comment on the private `replay_v2` imports (four after (2), not five).

## Checks

After the review fixes and the rebase onto `308ceed`:

- Passed: `ml/tests/test_validity_smoke.py` 21; full `ml/tests` 381 passed
  / 1 skipped (`yaml` not installed, pre-existing); `make
  validity-smoke-check`; `make hosted-rescore-check` (r4 contract
  unchanged, rescored artifact equal); `make phase03c-rescore-check` (0
  disagreements, heldout and dev); `make lint`; `make typecheck`; `make
  format-check`. (The full `ml/tests` run preceded a docstring-only move of
  the `replay_v2` note out of the import block for isort; the test module,
  `validity-smoke-check`, lint, typecheck and format-check reran after it.)
- Not run: `make preflight`, full `make test`.
