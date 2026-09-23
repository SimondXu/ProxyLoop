# Fix log: P2 ML/evaluation hygiene batch

Spec: `harness/context/fix-p2-ml-eval-hygiene-preflight.md`. Branch
`fix/p2-ml-eval-hygiene` from `origin/main` @ `5bedcce`. Audit items D3-7,
D3-9 (`repo-audit-D3.md`), D2-6, D2-7, D2-8 (`repo-audit-D2.md`); all five
verified present on `5bedcce` before any edit. No frozen module and no byte
under `data/` changed.

## Per item

- **D3-7 reason codes: fixed.** `pipeline._intrinsic_rejection` returns
  `schema_invalid` for a `ValidationError` (was `missing_provenance`; an
  absent `source` key still returns `missing_provenance` from the earlier
  check) and `hash_mismatch` for a stale `content_hash` or
  `semantic_fingerprint` (was `invalid_verifier_outcome`). Red first:
  `test_schema_invalid_candidate_is_not_labelled_missing_provenance` and
  `test_hash_mismatch_is_not_labelled_invalid_verifier_outcome` failed on
  `5bedcce` (`2 failed, 14 passed`), then passed. None of the eight pilot
  probes reaches either branch, so the Phase 02 quarantine manifest and
  quality report stay byte-identical (`data-pilot-check` green).
- **D3-7 `rejection_reasons`: recorded as a known limit.** The field is
  emitted in the committed `data/schemas/normalized-trajectory-v1.schema.json`
  (line 335), so removing it changes a committed artifact. Populating it has
  no sound place: quarantined candidates are emitted as dicts with
  `reason_codes`, not as `NormalizedTrajectory`, and changing that shape
  changes the committed quarantine manifest. Note for the follow-up: a
  candidate that arrives with a non-empty `rejection_reasons` is currently
  accepted (neither `_intrinsic_rejection` nor `_matches_environment` compares
  the field); not changed here because it needs a new reason code.
- **D3-9: recorded as a known limit.** The model-suffix match
  (`openai_frontier.py:587-590`) and the `error=str(exc)` writes
  (`:297, 311, 340, 354, 368`) live in `openai_frontier.py`, which is in
  `hosted_rerun._R4_EXECUTION_PATHS`. `runner_v2.py` (also frozen) constructs
  the base adapter directly, so a validating subclass or wrapper at a
  non-frozen call site (`validity_smoke.ValiditySmokeFrontierAdapter`) would
  cover only one path, and tightening the suffix needs a decision on which
  snapshot suffixes are legitimate (committed evidence records
  `gpt-5.6-terra-2026-07-09`). No live call is authorized, so the defect stays
  latent; committed error strings are at most 104 characters (audit).
- **D2-6: fixed with a non-frozen check.** `check_r2_artifacts`
  (`artifacts_v2.py`, frozen) still skips r2 semantic replay once r3 exists.
  r2 cannot replay clean by design: replaying it today yields exactly one
  mismatch, `untuned_fast_frontier_slow_medium`, the one condition whose
  episode rows r3 corrected. New
  `test_committed_r2_labels_replay_except_where_r3_corrects` replays the
  committed r2 through the public `replay_report_v2` and pins the mismatching
  conditions to the set r3 changed; r3 must replay clean. Sensitivity checked
  in a scratch script: flipping `end_to_end_valid` on one
  `untuned_fast_slow_off_r2` r2 row adds `untuned_fast_slow_off_r2: semantic
  replay mismatch`, which the test rejects. Runs under `make test`
  (`unit-test`).
- **D2-7: recorded as a known limit.** `failures.add("router_outcome_mismatch")`
  is at `runner_v2.py:1147` (frozen) and the label is inside the committed
  r2-r5 reports and the rescored r4; any fix changes committed report bytes.
- **D2-8: recorded as a known limit.** The constant `leakage_violation_count=0`
  writes (`runner_v2.py:636, 746, 836, 1224`), the never-set
  `policy_violation_count`, and the key-name leakage scan
  (`artifacts_v2.py:115-186`) are all in frozen files, and both counts are
  fields of committed reports.

## Verification (on the final diff)

- `uv run --project ml pytest -c ml/pyproject.toml ml/tests -q`: `393 passed,
  1 skipped` (skip is the pre-existing `yaml` import skip in
  `test_phase03c_training.py:360`).
- `make format-check`: exit 0. `make lint`: exit 0. `make typecheck`: exit 0.
  `make preflight-fast`: exit 0.
- `make test` (after `pnpm install --frozen-lockfile`, no `PROXYLOOP_TEST_*`
  set): exit 0; runtime `1127 passed, 46 skipped`, ML `393 passed, 1 skipped`;
  every evidence gate green. `drifted_since_r1`, `drifted_since_03b`,
  `drifted_since_bundle` are the pre-existing informational states
  (`harness/log/feat-runtime-1-1.md`).
- `git status --porcelain data/`: empty.
- Not run: `make preflight`, `make web-check`, the real-dependency gates (no
  runtime, API, workflow or web code changed).
