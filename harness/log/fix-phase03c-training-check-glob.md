# Fix log: the Phase 03C training check visits every committed run manifest

Spec: `harness/context/fix-phase03c-training-check-glob-preflight.md`.
Origin: I5 in `harness/code_review/phase-03c-stage3-decision.md` (left for a
bounded follow-up at the 03C gate). Branch `fix/phase03c-training-check-glob`
from `main` @ `dcc2b43`.

## What was wrong

`scripts/run_phase03c_training.py --check` (part of `make test`) globbed one
directory level and printed "consistent (1 checked)" while the two cloud
manifests (`cloud-run-01/train`, `smoke-01/train`) went unchecked. They are
a different format (`phase-03c-cloud-run-v1`, written by
`ml/training/phase03c_cloud/train.py`) that `check_run_manifest` does not
understand: a bare `rglob` would have turned `make test` red with four
format-mismatch problems each, not drift. The one-level glob was hiding a
missing checker.

## What changed

- `check()` walks the tree (`rglob`), requires the three committed paths
  (`EXPECTED_RUN_MANIFESTS`), dispatches on `schema_version`
  (`unknown_schema_version:<v>` otherwise), reports a malformed file as
  `malformed_manifest:<Exception>` and continues, and prints which checker
  ran per manifest.
- New `phase03c_training/cloud_manifest.py` `check_cloud_run_manifest`:
  every key train.py always writes; `config_hash` recomputed exactly as
  train.py does; `bundle.dataset_fingerprint` and `bundle.train_sha256`
  equal the committed cloud bundle manifest; `untuned_baseline` is the
  step-0 eval; `selected` is an eval with step > 0 and `policy_violation == 0`;
  the recorded delta equals selected − untuned exactly (train.py does not round).
- Tests (`ml/tests/test_phase03c_training.py`): all three manifests visited
  (fails on main: "1 checked"); config tamper; unknown schema; missing
  expected path; one single-field tamper each for delta drift, selection not
  in evals, bundle fingerprint, bundle train hash, missing key, policy
  violation; a malformed JSON file is reported, not raised.

## Review

Independent review (`reviewer`, Opus): **Approve**, no Blocking/Important.
Verified against train.py: key list exact, hash byte-identical, the two
selection rules cannot fire on a valid run, float equality valid. Minors 1–4
applied (policy_violation filter, malformed-as-problem, train_sha256 binding,
tamper tests); not re-reviewed (tightening only).

## Known limits

- `adapter_sha256` / `merged_sha256` are not checked: the weights are not committed.
- The full checkpoint tie-break rule is not re-derived (it depends on which
  checkpoint directories existed on the cloud volume).
- Every cloud manifest is bound to the currently committed bundle;
  regenerating the bundle flags both historical runs as
  `bundle_fingerprint_mismatch` — an intended drift signal that needs an
  explicit decision, not a silent update.
- `CLOUD_RUN_MANIFEST_KEYS` mirrors train.py by hand; a new train.py key must
  be added there (extra keys are tolerated).

## Checks

`make phase03c-training-check`: consistent (3 checked). Final
`make preflight` output is in the PR body.
