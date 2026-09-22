# Fix log: hosted-evaluation artifacts survive evaluator evolution (G2b)

Spec: `harness/context/fix-hosted-evaluator-evolution-preflight.md`.
Design: `harness/context/group2-evaluator-proposal.md` §G2b/§3 (option c).
Programme: `harness/context/audit-remediation-decisions.md` (decisions 5,
6). Branch `fix/hosted-evaluator-evolution` from `main` @ `9c0f0c0`.
Brings forward audit P1 rows D2-2/D2-5 because P0-6 cannot land without
them.

## What changed

- New `ml/evaluation/src/proxyloop_evaluation/hosted_rescore.py`:
  `check_r4_integrity` (every non-replay property of the r4-era gate,
  calling the frozen module's helpers), `execution_contract_state`
  (`unchanged` / `drifted_since_r4` with `drifted_paths`, plus a
  `pins_stale` self-check that the 12 pinned per-file hashes still
  aggregate to r4's stored fingerprint; a missing frozen file is drift,
  not an exception), `derive_rescored_r4` (re-reads r4's stored raw
  outputs through the **current** evaluator via `replay_v2._replay_condition`
  and `_preserve_source_evidence`; deterministic — inner `generated_at`
  copies r4's), `check_rescored_artifact` (byte-equal to the in-memory
  derivation, `source_report_fingerprint` bound to the committed r4, and
  `rows_changed_vs_r4` equal to `_EXPECTED_ROWS_CHANGED_VS_R4` — all seven
  conditions `()` in this PR). `RescoredReportV2` is a sibling wrapper
  around `EvaluationReportV2` because adding a field to the latter would
  change the frozen `report_fingerprint_v2` of committed r2/r3.
- New `scripts/run_phase_03a1_hosted_rescore.py` (`--write` / `--check`)
  and the committed `data/evaluation/phase-03a1-r4-rescored-report.json`
  (row-for-row equal to r4 with the unchanged verifier).
- `Makefile`: `hosted-rerun-check` → `hosted-rescore-check`; new
  `hosted-rescore`, `hosted-rescore-check`, `baselines-historical-check`;
  `make test` runs the historical r1 check instead of the r1 replay. The
  r4-era gate `run_phase_03a1_hosted_rerun --check` stays runnable.
- `models.py`: `EvaluationReportV2` accepts `schema_version
  "phase-03a1-r4-rescored-v1"` (requires `source_report_fingerprint`, a
  `phase-03a1-rescore::` `evaluator_version`, zero new dispatches).
- `artifacts.py`: `check_baseline_artifacts(root, *, replay=True)` and
  `check_baseline_artifacts_historical`; `scripts/run_phase_03a1_baselines.py
  --check-historical`.
- `environment.py`: `PROVIDER_VERIFIER_VERSION = "phase-01b-verifier-v1-label"`.
- `tests/contract/test_phase_03a1_baselines_architecture.py`: asserts
  `baselines-historical-check` in `make test` (the old assertion pinned
  the r1 replay).
- `docs/ml-evidence.md`: r1 historical / r4 rescore wording; r5 unchanged.

## Evidence

- `rows_changed_vs_r4`: 0 for all seven conditions; contract state
  `unchanged` (r4 and current `6b50437f…683b2`).
- 12 frozen files: `git diff --stat` empty; `hosted-rerun-source-check`
  green. r1–r5 committed reports unchanged.
- Independent review (`reviewer`, Opus): **Approve**. Verified the pinned
  hash aggregate equals r4's stored fingerprint by the frozen formula;
  tamper cases (flipped row with refreshed fingerprints, wrong source
  fingerprint, the `test_hosted_rerun` tamper set) rejected; the
  derivation runs the current verifier (monkeypatched
  `_verify_decision` → 98 calls, non-empty deltas). Important 1 (a
  laundered tamper — edit r4, refresh, `make hosted-rescore` — passed the
  gate) fixed by the `_EXPECTED_ROWS_CHANGED_VS_R4` assertion with a
  regression test; Important 2 fixed by the verifier-sensitivity test;
  minors 5/6 (missing file → drift, `pins_stale`) applied. Not applied:
  `docs/development.md` target list (spec limits docs to
  `ml-evidence.md`; follow-up with P2 hygiene), the contract test
  `test_phase_03a1_hosted_rerun_architecture.py:35` still matching the old
  script name by substring (follow-up), `check_hosted_rerun_sources`'s
  static constant checks not repeated in the new gate.

## Checks

- Passed: `ml/tests/test_hosted_rerun.py` + `test_hosted_rescore.py` 45;
  `PYTHONPATH=. make hosted-rerun-source-check hosted-rerun-check
  hosted-rescore-check errata-check validity-smoke-check
  baselines-historical-check`; the full `PYTHONPATH=. make test`;
  `tests/contract` 58; `make lint`, `make typecheck`, `make format-check`,
  `make check-layout`.
- Passed: `make preflight` — runtime 324 / 42 gated skips, ML 352 / 1
  skipped, web 51, all gates valid, r1 "intact (not replayed)", r4
  contract unchanged, rescored artifact equal.
