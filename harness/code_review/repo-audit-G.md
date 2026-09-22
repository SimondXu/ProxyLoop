# Repo audit — Lane G: build, gates, scripts

Reviewer: `explorer` (Sonnet, medium), read-only. Recorded by the root
orchestrator from the lane's evidence card; root verification verdicts at
the end.

## Gate classification

| Target / job | What it compares | Class |
|---|---|---|
| `contracts-check` (`generate_contracts.py --check` + `tsc --noEmit`) | regenerates JSON Schema, TypeScript, fixture into a temp dir and byte-compares | semantic regeneration + compare |
| `hosted-rerun-check` (`hosted_rerun.check_hosted_rerun_artifacts`) | replays `matrix_result` through `replay_report_v2` with fresh fixtures | semantic replay |
| `benchmark-check`, `data-pilot-check`, `harness-check`, `phase03b-readiness-check` | regenerate from simulator/model classes and compare | semantic regeneration + compare |
| `baselines-check` (`artifacts.check_baseline_artifacts`) | report's own `report_fingerprint` recomputed over its own payload; cross-file fingerprint equality with manifest/episodes/ceiling; truthfulness rules on cost/call counts | self-referential + cross-file consistency (no oracle/model re-run) |
| `errata-check`, `validity-smoke-check`, `phase03c-errata` | same pattern as above for r2/r3/r5 and 03C errata | self-referential + cross-file (03C erratum re-derives from stored raw outputs) |
| `phase04d-profile-check` | asserts `p95 >= p50`, `timeout_rate > 0` on a freshly generated report; no committed artifact | self-consistency only, no baseline |
| `check-layout` (`validate_layout.py`) | explicit allowlist of paths that must exist | presence-only |
| `lock-check` | `uv lock --check` ×2, pnpm frozen offline | real reproducibility check |
| CI `phase-gate` | `make preflight` + `postgres-check` + `phase04d-check` + `phase04d-profile-check` + `phase05a-check` + `phase06b1-check` with Postgres/Temporal services; runs on every PR and push to main; no manual-dispatch jobs | superset of local preflight |

## Findings

**G-1 (Minor) — `make preflight` silently skips 36 DB/Temporal integration tests.**
`Makefile:43` `preflight: validate lock-check`; `unit-test` collects
`tests/integration` unconditionally, and `test_phase_04c_persistent_case_store.py:132-135`,
`test_phase_05a_case_runtime.py:234`, `test_phase_05a_temporal_workflow.py:103-113`,
`test_phase_06b1_temporal.py:51-62` `pytest.skip(...)` without
`PROXYLOOP_TEST_DATABASE_URL`. Claim weakened: `CLAUDE.md` names `make
preflight` the "final local gate". Reproduction: `make preflight` with the
env vars unset reports "291 passed, 33 skipped" and exits 0. Direction: a
`preflight-full` target or a skip-count assertion so the local gate cannot
pass silently without the real-dependency gates; harness logs should name
which of the two ran.

**G-2 (Minor) — `contracts/README.md` claims OpenAPI artifacts that nothing generates.**
`contracts/README.md:3` vs `contracts/openapi/` containing only `.gitkeep`;
`generate_contracts.py` produces JSON Schema, TypeScript, fixture only.
Direction: drop the OpenAPI claim or generate it from the FastAPI app.

**G-3 (Minor) — `phase04d-profile-check` has no baseline and uses bare `assert`.**
`scripts/run_phase_04d_control_plane_profile.py:176-186`: three `assert`
statements on a freshly generated report; no committed artifact to diff.
`python -O` would disable the check entirely. Direction: compare against a
committed profile schema/shape and raise instead of `assert`.

**G-4 (Note) — `baselines-check` and the r2/r3/r5 checks are consistency checks, not replays.**
`ml/evaluation/src/proxyloop_evaluation/artifacts.py:45-95`. This is
expected for hosted results that cannot be regenerated without spend, and
`docs/development.md:53` says so ("replay committed reports with zero
external model calls"), but the phrase "replay" overstates it for these
targets: only `hosted-rerun-check` replays. The class of bug from 03A1
(model/oracle input mismatch) is not detectable by these targets.

**G-5 (Note) — `validate_layout.py` is an existence allowlist.**
A new `src`/`tests` directory not added to `PYTHON_PATHS` /
`ML_PYTHON_PATHS` (`Makefile:15-38`) would be neither linted, typed, nor
tested, and nothing would fail. No such drift exists today
(`model_gateway`, `ml/serving`, `ml/training`, `ml/configs`, `ml/manifests`
are `.gitkeep` placeholders).

**G-6 (Note) — `compose.yaml:20-35` hard-codes `proxyloop/proxyloop` for `postgres-test`** and CI reuses the literal. Local/CI only; not flagged as dev-only anywhere.

## Checks run / not run

Run: static reads of `Makefile`, `ci.yml`, `compose.yaml`, every `--check`
function in `scripts/*.py`, `validate_layout.py`, `generate_contracts.py`;
`find` vs Makefile path lists. Not run by this lane: `make preflight` (run
by the baseline agent, passed), `make -n`. Not read:
`phase03b_experiment.py` / `phase03c_experiment.py` (out of scope).

## Open questions

- Whether `check_phase03b_artifacts` inside the excluded
  `phase03b_experiment.py` regenerates or is self-referential.

## Root verification (2026-09-21)

| Id | Verdict | Evidence inspected |
|---|---|---|
| G-1 | confirmed | `Makefile:43`, baseline run output (33 skipped, exit 0), CI steps in `docs/development.md:60-65` |
| G-2 | confirmed | `contracts/README.md:3`; `ls contracts/openapi` → `.gitkeep` only |
| G-3 | confirmed | `run_phase_04d_control_plane_profile.py:173-186` |
| G-4 | confirmed as Note | `artifacts.py:45-95` read in full |
| G-5, G-6 | accepted as Notes | — |

Net: the gates are honest about what they check and CI is stronger than the
documented local gate; no Blocking or Important finding in this lane. The
practical risk is G-1: a local "preflight passed" claim in a harness log
does not cover PostgreSQL/Temporal behaviour unless the real-dependency
targets are named separately.
