# Feature log: model-backed Fast under Temporal and the 07A `FAST_BACKEND` flag (PR-11)

Spec (implementer, 2026-09-24): `harness/context/pr11-fast-under-temporal-preflight.md`.
Build-plan item PR-11 (stage 1c). Branch `feat/pr11-fast-under-temporal` from
`main` @ `a8fdf5b` (#97, PR-9a; PR-3 #92 included). PR-9b (the gateway) is not
on `main`; CI and this log use only the in-test fake gateway.

Non-goals: no change to `workflow.py` (no Workflow command, timer, patch,
activity option, or retry policy), `runtime.py` (PR-13), `app.py` (PR-12),
`agent_core`, the `local_fast` package, `contracts/`, or any `ml/` file.

## Decisions (spec §2)

- D1: the worker selects Fast from `PROXYLOOP_FAST_BACKEND` through
  `fast_adapter_from_environment` (same refusal matrix and identity probe as
  the API), before it opens the database.
- D2: the API drops its Temporal refusal; it probes the same gateway and
  labels `adapter_mode`, never calls Fast in Temporal mode, and cannot see the
  worker's selection (traces are the authority; recorded limit).
- D3/D4: Fast ≤ 25 s inside the 30 s activity and the 30 s Next proxy; a
  typed Fast failure applies the command, so the activity completes and is
  not retried; a validation reject stays non-retryable `model_path`.
- D5 (recommended option A, root to confirm): channel commands keep scripted
  Fast on a second `ThinAgentRuntime` over the same repository; the outbound
  body stays `BOUNDED_FAST_STATUS_TEXT` and the model is never called on the
  channel path (PR-8 I7 byte-for-byte). Options B (model text outbound) and C
  (fail closed) are in the spec.
- D6: `FAST_BACKEND=distilled|untuned make portfolio-demo` expects PR-9b's
  gateway; `serve` probes it before starting anything and refuses otherwise.
- D7: no replay fixture needed (no Workflow change).

## What changed

- `workflow_worker/activities.py`: `activity_adapter_from_environment(environ)`
  (worker refusals → `fast_adapter_from_environment` → PostgreSQL repository →
  one Runtime, plus a scripted channel Runtime when Fast is local);
  `CaseCommandActivityAdapter(..., channel_runtime=None)` routes
  `ingest_channel_event` / `record_channel_delivery` to it;
  `runtime_from_environment` keeps its signature and returns the Case Runtime;
  `_get_default_adapter` uses the new builder.
- `workflow_worker/worker.py`: `create_worker` uses the new builder.
- `workflow_worker/pyproject.toml` + `runtime/uv.lock`: workspace dependency on
  `proxyloop-local-fast` (two lock lines; no third-party change).
- `api/config.py`: the Temporal refusal of a local backend is removed (no
  `app.py` edit).
- `scripts/run_phase_07a_portfolio_demo.py`: `serve --fast-backend
  {scripted,distilled,untuned}`; `build_demo_environment(..., fast_backend=)`
  sets `PROXYLOOP_FAST_BACKEND` for every child; `check_fast_backend(env)`
  runs before ports/Compose/Web/host processes; the banner prints the backend
  and label.
- `Makefile`: `FAST_BACKEND ?= scripted`, `portfolio-demo` passes
  `--fast-backend "$(FAST_BACKEND)"`; `phase05a-check` runs
  `test_fast_under_temporal.py`.
- `scripts/check_gated_skips.py`: pin `test_fast_under_temporal.py: 3`
  (63 → 66).
- Tests: new `tests/integration/test_fast_under_temporal.py`; launcher tests in
  `test_phase_07a_portfolio_demo.py`; PR-9a's
  `test_temporal_refuses_a_local_fast_backend` removed from
  `test_local_fast_config.py` (the behaviour this PR lifts; replaced by the
  two Temporal API tests in the new file).
- Docs: `docs/architecture.md` (new "Local Fast backend under Temporal
  (PR-11)" section; two PR-11 forward references resolved; the Temporal mode
  sentence), `docs/portfolio-demo.md` (the flag), `docs/development.md` (the
  variables under Temporal, the gated list, 66, the `phase05a-check` row),
  `harness/context/audit-remediation-status.md` §0 (PR-11 row).

## Red on `main` @ `a8fdf5b` (tests written first)

`tests/integration/test_fast_under_temporal.py`: 10 failed, 6 passed, 3 skipped.

- Failed for the intended reasons: the five worker refusal cases (4 × the
  sentinel `AssertionError: the worker opened the database before refusing`,
  i.e. the worker ignored the variable, and the absent/mismatched gateway
  case), `test_worker_selects_the_labelled_local_backend` and
  `test_worker_scripted_default_builds_one_runtime` (`AttributeError`: no
  `activity_adapter_from_environment`),
  `test_channel_ingest_under_a_local_backend_keeps_the_constant_body` (same),
  and both Temporal API tests (`ValueError: Temporal orchestration requires
  PROXYLOOP_FAST_BACKEND=scripted`).
- Passed on `main` by design (guarantees and pins, not red): the three
  `test_a_fast_failure_applies_the_command_without_an_activity_error` cases
  (9a's capture already makes the activity return), the `RUNTIME_MODE=model`
  refusal, `test_one_local_runtime_for_every_command_would_fail_channel_ingest`
  (documents the `model_path` hazard D5 removes), and the budget pin.

`tests/integration/test_phase_07a_portfolio_demo.py`: 5 failed, 16 passed
(`build_demo_environment` has no `fast_backend`, no `check_fast_backend`,
`start_demo` has no `fast_backend`, `serve` has no `--fast-backend`, the
Makefile passes no flag).

## Green (on the branch, before commit)

- Focused: `test_fast_under_temporal.py`, `test_local_fast_config.py`,
  `test_phase_07a_portfolio_demo.py`, `test_phase_06b1_workflow_worker.py`,
  `test_fast_failure_fallback.py`, `test_local_fast_adapter.py`,
  `test_gated_skips_check.py`, `test_phase_04b_model_runtime.py`:
  202 passed, 3 skipped (the three gated tests).
- The three gated time-skipping bodies (G1 busy, G1 slow, G2) were also
  called directly from a scratch runner, with no `PROXYLOOP_TEST_*` variable
  set and no database (in-memory repository, the cached process-local
  time-skipping server): all passed (1.7 s, 1.8 s, 0.7 s). This is not the
  `phase05a-check` gate; that run stays with the DB lane.
- `make lint`: passed. `make format-check`: passed after `make format`
  (two test files reflowed). `make typecheck`: passed (75 and 59 source
  files).
- `make preflight`: exit 0. Runtime pytest 1614 passed, 66 skipped; ml pytest
  397 passed, 1 skipped; every `*-check` in `make test` passed; web vitest 189
  passed; `lock-check` passed (`runtime/uv.lock` gains only the worker's
  workspace edge; `ml/uv.lock` unchanged); gated-skip check "match the pinned
  66 per file".
- Not run (by instruction): `make postgres-check`, `make phase05a-check`
  (runs G1/G2 under the gate), `make phase06b1-check`. Manual (needs PR-9b's
  gateway): `make local-fast-gateway BACKEND=distilled`, then
  `FAST_BACKEND=distilled make portfolio-demo`, Scene A and Scene B.

## Remaining

- Root: confirm D5 option A (channel commands keep scripted Fast; constant
  outbound body) or choose B/C (spec §2 D5).
- DB lane serially; independent review; PR; CI; merge.
- Recorded limits (spec §7): API label drift if the worker is started with
  another value; queued same-Case Fast calls can exceed the 30 s Next proxy;
  a slow database plus a 25 s Fast call can exceed the activity
  start-to-close; the `model_path` 409 message still says "unavailable in
  Temporal mode" (in `app.py`, left for PR-12's window).
