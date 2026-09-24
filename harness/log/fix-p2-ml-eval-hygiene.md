# Fix log: P2 ML/evaluation hygiene batch

Spec: `harness/context/fix-p2-ml-eval-hygiene-preflight.md`. Branch
`fix/p2-ml-eval-hygiene` from `origin/main` @ `5bedcce`. Audit items D3-7,
D3-9 (`repo-audit-D3.md`), D2-6, D2-7, D2-8 (`repo-audit-D2.md`); all five
verified present on `5bedcce` before any edit. No frozen module and no byte
under `data/` changed.

## Per item

- **D3-7 reason codes: fixed.** `pipeline._intrinsic_rejection` now labels
  each rejection by its actual cause (codes decided by the root orchestrator
  after independent review):
  - `source` absent or `None`: `missing_provenance` (a null `source` was
    `schema_invalid` on the WIP commit);
  - `ValidationError`: `schema_invalid` (was `missing_provenance`);
  - non-empty `rejection_reasons`, checked after schema validation so
    `schema_invalid` still wins: `declared_rejection` (was accepted);
  - `derivation_parent_id` names no scenario: `unknown_derivation_parent`
    (was `split_mismatch`);
  - `source`/`generation` present but differ from the expected record:
    `provenance_mismatch` (was `missing_provenance`);
  - stale `content_hash` or `semantic_fingerprint`: `hash_mismatch` (was
    `invalid_verifier_outcome`).
  Red first: on the WIP commit `test_schema_invalid_candidate_is_not_labelled_missing_provenance`
  and `test_hash_mismatch_is_not_labelled_invalid_verifier_outcome` failed
  (`2 failed, 14 passed`). In the review round
  `test_declared_rejection_reasons_are_not_accepted` (candidate was accepted),
  `test_replaced_provenance_is_provenance_mismatch`,
  `test_unknown_derivation_parent_is_not_labelled_split_mismatch`,
  `test_null_source_is_missing_provenance`, and the updated expectation in
  `test_frozen_source_and_environment_verification_cannot_be_replaced`
  failed (`5 failed, 32 passed` across the two ML test files), then all passed
  (`37 passed`). None of the eight pilot probes reaches a changed branch
  (probe 01 deletes `source`; probe 07 changes only `lineage.split`; every
  probe has empty `rejection_reasons`), so the Phase 02 quarantine manifest,
  quality report, and `EXPECTED_REJECTION_CATEGORIES` in
  `tests/integration/test_phase_02_artifacts.py` are unchanged
  (`make data-pilot-check` green).
- **D3-7 `rejection_reasons` field: accept-gap fixed; deletion deferred.** A
  declared rejection is now quarantined (above). Deleting the unused field
  stays deferred because it is emitted in the committed
  `data/schemas/normalized-trajectory-v1.schema.json` (line 335).
- **D3-7 limit (audit N1, out of scope):** the `_matches_environment`
  fallback in `curate_candidates` (`pipeline.py:566`) still labels any
  non-regenerable row `invalid_verifier_outcome`.
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
  replay mismatch`, which the test rejects. After review the test also pins
  the single corrected episode: the differing fields are exactly
  `{failure_codes, route_agreement}` and the `failure_codes` symmetric
  difference is exactly `{router_outcome_mismatch}`. Sensitivity checked on
  scratch copies of the test: appending a failure code to that r2 episode
  fails the `failure_codes` pin, and changing its `fast_raw_output` fails the
  field-set pin. Runs under `make test` (`unit-test`).
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

## Update to `origin/main` (2026-09-24)

- `git merge origin/main` twice (no rebase, no force-push): `f989613` (#70,
  #71), then `f818b61` (#72), which landed while verification ran. Both merges
  were conflict-free; neither touched `ml/` or `data/`. The branch diff against
  `origin/main` is still the three `ml/` files plus this log and the spec.
- Re-verified on the merged tree `dfc21b9`: `make format-check lint typecheck`
  exit 0; `make preflight-fast` exit 0; `make test` (no `PROXYLOOP_TEST_*` set)
  exit 0, runtime `1174 passed, 46 skipped`, ML `393 passed, 1 skipped`, the
  same three informational drift states. The main checkout collects 391 ML
  tests (390 passed + 1 skipped) and this worktree 394 (393 + 1); the one
  `make test` run that reported `390 passed, 1 skipped` matches main's
  collection (root orchestrator: it ran on main after a cwd reset) and is not
  evidence for this branch.
- `git status --short data/`: empty. `git diff --stat origin/main -- ml/ data/`:
  only `pipeline.py`, `test_pipeline.py`, `test_phase03a1_erratum_artifacts.py`.

## Review round 1 (Request Changes: I-1, M-1, M-2, M-3)

- Applied the root decisions above (`declared_rejection`, the three
  relabels, the r2→r3 episode pin, the 390 note). `:566` untouched.
- Verification on the final diff: the two ML test files `37 passed`;
  `make data-pilot-check` exit 0; `make format-check lint typecheck` exit 0;
  `make preflight-fast` exit 0; `make test` (no `PROXYLOOP_TEST_*`) exit 0,
  runtime `1174 passed, 46 skipped`, ML `397 passed, 1 skipped` (398
  collected), the same three informational drift states.
- `git status --short data/`: empty. No path in
  `hosted_rerun._R4_EXECUTION_PATHS` is in the diff; `git diff --stat
  origin/main -- ml/ data/` lists only `pipeline.py`, `test_pipeline.py`,
  `test_phase03a1_erratum_artifacts.py`.
- Not run: `make preflight`, `make web-check`, the real-dependency gates.
