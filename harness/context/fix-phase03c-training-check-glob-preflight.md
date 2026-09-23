# Fix: Phase 03C training `--check` covers every committed run manifest (I5)

Bounded follow-up to I5 in `harness/code_review/phase-03c-stage3-decision.md`.
Branch `fix/phase03c-training-check-glob` from `main` (`dcc2b43`).

## Defect

`scripts/run_phase03c_training.py` `check()` globbed `*/run-manifest.json`,
so `make phase03c-training-check` (part of `make test`) reported
`consistent (1 checked)` while visiting only `training/smoke/`. The cloud
runs `cloud-run-01/train/` and `smoke-01/train/` sit two levels down.

## Finding: two manifest formats

A recursive probe with the existing `check_run_manifest` failed both cloud
manifests (`schema_version_mismatch`, `deviation_missing`,
`fingerprint_drift`, `config_or_recipe_missing`). No data had drifted: they
are `phase-03c-cloud-run-v1` written by `ml/training/phase03c_cloud/train.py`,
while `check_run_manifest` validates only the local MLX
`phase-03c-training-run-v1`. The old glob skipped a format it could not check.

## Frozen design (root decision: dispatch by `schema_version`)

1. `check()`: `rglob`, sorted; problems labelled with the path relative to
   `TRAINING_DIR`; `EXPECTED_RUN_MANIFESTS` lists the three committed paths
   and a missing one is `missing_expected_manifest`; extras are checked too;
   an unknown `schema_version` is `unknown_schema_version:<value>`, never
   skipped. Each manifest prints its schema and checker; the summary prints the count.
2. `phase-03c-training-run-v1` -> `check_run_manifest` (unchanged).
3. `phase-03c-cloud-run-v1` -> new `phase03c_training/cloud_manifest.py`
   `check_cloud_run_manifest(path)`: (a) all 26 keys `train.py` always writes
   (none is smoke-conditional; `selected` and its delta are `None` together);
   (b) `config_hash == sha256(json.dumps(config, sort_keys=True))`; (c)
   `bundle.dataset_fingerprint` equals the committed
   `cloud-bundle/bundle-manifest.json`; (d) `untuned_baseline` is the step-0
   eval, `selected` is a step > 0 entry of `evals`, and
   `selected_minus_untuned_act_agreement` is exactly the difference (train.py
   does not round). Known limit: `adapter_sha256` / `merged_sha256` are not
   checked because the weights are not committed.

## Tests (`ml/tests/test_phase03c_training.py`)

- visits all three committed manifests (red on old code: `1 checked`);
- a tampered cloud `config` yields exactly `config_hash_drift`;
- unknown `schema_version` fails; a missing expected path fails.

## Review follow-ups

- `selected` must have `policy_violation == 0` (select_checkpoint's filter;
  the tie-break is not re-derived) -> `selected_has_policy_violation`.
- `bundle.train_sha256` must equal the committed bundle's
  `files["train.jsonl"].sha256` -> `bundle_train_sha256_mismatch`.
- `check()` reports unparsable input as `malformed_manifest:<ExceptionType>`
  and continues; the run still exits non-zero.

Known limits: every cloud manifest is bound to the currently committed
bundle; regenerating the bundle will flag both historical cloud runs as
`bundle_fingerprint_mismatch`, an intended drift signal that requires an
explicit decision. Adapter and merged-weight hashes are not checked.
