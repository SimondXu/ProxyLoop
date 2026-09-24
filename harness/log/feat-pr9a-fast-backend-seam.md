# Feature log: the Fast backend seam, R-19, the HTTP Fast adapter, and `PROXYLOOP_FAST_BACKEND` (PR-9a)

Spec (frozen by the root, 2026-09-24, root answers Q1–Q12):
`harness/context/pr9-local-distilled-fast-design.md`, committed here byte-identical
to PR-9b's copy (blob `2b604619`), so whichever branch merges second gets a no-op.
Build-plan item PR-9a (decisions 16–18, stage 1b runtime half). Branch
`feat/pr9a-fast-backend-seam` from `main` @ `29c8671` (PR-7's trace log, PR-8a's
gate and split report, PR-6's app lock, PR-3's channel re-drive included).

Non-goals, per the spec §6.5: no change to `app.py`, `workflow.py`,
`activities.py`, `postgres_repository.py`, `contracts/`, `validate_fast_result`,
`project_fast_view`, PR-8's gate rules, `ScriptedFastAdapter`, or any `ml/` file
(the gateway, conversion, parity and split reports are PR-9b). CI uses only the
in-test fake gateway; no model runs.

## What changed

- `agent_core/observation.py` (R-19): `classify_provider_offer(offer, *,
  provider_id, case_id) -> SafeOffer | tuple[str, ...]`, total over contract-valid
  `ProviderOffer`s, codes in the pre-R-19 check order (`offer_case_mismatch`,
  `offer_provider_mismatch`, `offer_fee_sum_negative`,
  `offer_features_duplicate`). `SafeObservationAdapter.build` keeps its signature
  and delegates, raising the pre-R-19 message for the first code.
- `agent_core/fast_observation.py` (new): `FAST_OBSERVATION_VERSION =
  "fast-observation-v1"`, `ObservationRefusal`, `fast_public_observation(snapshot)`.
  Declared Provider-state defaults (D3); refusal codes for a missing bill,
  Provider event or offer, mixed Providers, repeated offer ids or Case tokens,
  and every classifier code.
- `agent_core/local_fast_wire.py` (new, stdlib JSON only): the single owner of
  `local-fast-wire-v1`: request encode/decode (the gateway side decodes with it),
  response encode/decode, identity decode with the fingerprint recomputed,
  allow-listed status and detail codes, `WireError(code)`. The request, response,
  and identity shapes match what PR-9b's gateway (`afeec4d`) already emits.
- `agent_core/interfaces.py`: `FAST_ADAPTER_FAILURE_CODES` (the seven codes),
  `FAST_ADAPTER_FAILURE_DETAIL_CODES`, `FastAdapterFailure(reason_code, *,
  detail_code, usage)` (codes outside the allow-lists → `ValueError`),
  `ObservingFastAdapter`, `LabelledFastBackend`.
- `agent_core/coordinator.py`: `CaseCoordinator(..., capture_fast_failures=False)`;
  `CoordinatorOutcome.fast_failed`. An `ObservingFastAdapter` gets
  `fast_public_observation` of the same snapshot; a refusal raises
  `FastAdapterFailure("fast_input_unrenderable", detail_code=<first code>)`
  before the adapter is called. With capture, a `FastAdapterFailure` becomes a
  rejected Fast audit plus a `FAILED` trace (reason codes, `output_ref=None`,
  `output_schema_version="none"`, reported tokens, the call window as latency).
  Any other exception propagates; without capture so does the failure. The
  untraced (1.0, ML) path still calls `fast.decide(view)` for every
  non-observing adapter.
- `case_runtime/runtime.py` (the three spec-assigned spots only):
  `_coordinator` passes `capture_fast_failures=True`; delivery treats
  `fast_failed` like `fast_disclosure_rejected` (fallback line, command applies,
  no `fast` echo); `AdapterMode` gains `local_distilled_candidate` and
  `local_untuned_baseline`, inferred from `LabelledFastBackend` when Slow is
  scripted.
- `runtime/packages/local_fast` (new workspace member, `proxyloop_local_fast`):
  `LocalFastHttpAdapter` (`connect` probes `/v1/identity` and fails closed; loopback
  `http://` origins only, no credential, no redirect; per-response identity
  check; strict `FastModelOutput`; non-empty `fact_updates` refused; compiled
  against the runtime's view) and `fast_adapter_from_environment`
  (`PROXYLOOP_FAST_BACKEND`, `PROXYLOOP_FAST_GATEWAY_URL`,
  `PROXYLOOP_FAST_TIMEOUT_S`, default 20, cap 25). `LocalFastStartupError` for an
  absent, invalid, or mismatched gateway.
- `api/config.py`: a local backend only with `PROXYLOOP_RUNTIME_MODE=scripted`;
  Temporal refuses any non-scripted Fast backend until PR-11.
- Wiring: `runtime/pyproject.toml` (member), `runtime/uv.lock` (+1 package),
  `runtime/services/api/pyproject.toml`, `Makefile` (`PYTHON_PATHS`, typecheck
  list).
- Tests (new): `test_fast_failure_fallback.py` (F1, AC2 per code, A15, A16, A17,
  A21), `test_fast_observation_renderer.py` (F2, AC4, A18 differential fuzz),
  `test_local_fast_config.py` (F3, AC3, A13, A14), `test_local_fast_adapter.py`
  (A1–A12, A14, A19, A20, wire strictness), helper `local_fast_fake_gateway.py`,
  goldens `tests/fixtures/local-fast-wire/*.json`. No existing test edited; no
  DB-gated test added (the per-file pin is unchanged).
- Docs: `docs/architecture.md` ("Local opt-in Fast backend (PR-9a)", the
  `ml/serving` line, the trace-gap sentence), `docs/development.md` (the three
  variables), `CONTEXT.md` ("Fast Backend", "Local Opt-in Candidate"),
  `harness/context/audit-remediation-status.md` (§0 row, R-19 in §4a).

## Red (on `main` @ `29c8671`, before any production edit)

Collection of the three red files (F1–F3), `pytest -q` on the new test files:

```
E   ImportError: cannot import name 'FAST_OBSERVATION_REFUSAL_CODES' from 'proxyloop_agent_core'
E   ModuleNotFoundError: No module named 'local_fast_fake_gateway'
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
```

Behavioural red, same tree (scratch probe, not committed):

```
F1 red: adapter failure escaped the command (Timeout); fast traces=0
F2 red (P3): SafeObservationAdapter.build raised ValueError: fees_minor must be a non-negative integer
F3 red: 'bogus' (mode scripted) started a Runtime, adapter_mode=scripted
F3 red: 'distilled' (mode model) started a Runtime, adapter_mode=model
```

## Green

Focused (new files plus the spec §6.6 list: `test_fast_dialogue_delivery`,
`test_model_trace_producer`, `test_persisted_claim_and_traces`,
`test_fast_slow_split_report`, `test_direct_mode_command_path`,
`test_phase_04d_control_plane_operations`, `test_browser_projection_allowlist`,
`test_phase_04a/04b/05a`, `test_phase_03a1_agent_core`,
`test_phase_01b_observation`, `test_b1_9_total_offer_policy`): 335 passed,
2 skipped (DB-gated).

## Byte identity

After `make test` and `make preflight`: `git status --porcelain -- data ml
contracts scripts` is empty and `git diff --stat origin/main -- ml data contracts
scripts` is empty, so no committed artifact, frozen ml file, `ml/pyproject.toml`,
or `ml/uv.lock` moved. Every `*-check` in `make test` passed on the committed
bytes, including `fast-slow-split-check` (`data/evaluation/fast-slow-split-scripted.json`
blob `ed00058a` = `origin/main`), `negotiation-check`, `hosted-rerun-check`,
`phase03c-smoke-check` and `phase03c-rescore-check`. `uv lock --project ml
--check` passes; `runtime/uv.lock` gains only the new workspace member. The PR-8
split report needed no new field: it already records `fast_result="failed"` and
`fallback_cause="failure"` (spec §5.2 amendment), and a test here drives it.

## Checks

On the final tree, with no `PROXYLOOP_TEST_*` variable set:

- `make lint`: passed (runtime and ml ruff, `git diff --check`).
- `make typecheck`: passed (runtime 75 source files, ml 59).
- `make test`: passed, exit 0. Runtime pytest 1559 passed, 63 skipped (all
  DB/Temporal-gated); ml pytest 397 passed, 1 skipped; every `*-check` target
  passed.
- `make preflight`: passed, exit 0 (format-check, lint, typecheck, test,
  check-layout, web-check with 140 Web tests and a production build, lock-check,
  compileall, compose config). Gated-skip counts match the pinned 63 per file.
- Not run here (queued lane, per the task): `make postgres-check`,
  `make phase05a-check`, `make phase06b1-check`. `runtime.py` and `api/config.py`
  changed, so these are required before merge. No DB-gated test was added.
- Not run: independent review, `/security-review` (new loopback HTTP client and
  failure path), any real gateway or model (PR-9b's manual lane).

## Decisions and assumptions (implementer; root to confirm)

- `FastAdapterFailure.detail_code` is one code; for a renderer refusal with
  several codes the trace carries the first (check order). The full list is in
  `ObservationRefusal` only.
- The detail allow-list is the union of the gateway's `invalid_output` and
  `unrenderable` details (taken from PR-9b's `gateway_core.py`), the wire error
  codes, the client's own codes, and the observation refusal codes. An unknown
  gateway detail code is a protocol error (`detail_code_unknown`), not passed
  through.
- The decide-request golden is pinned by a decode/re-encode round trip, not by
  equality with a live runtime request, so unrelated scripted-content changes
  (for example PR-13's Slow) do not move it; the response and identity goldens
  are pinned byte for byte and the identity goldens equal PR-9b's
  `with_generator` identities (recomputed from the frozen ml constants).
- The runtime `FastModelOutput` schema golden differs from the ml frozen copy
  only in the class docstring (`description`); the structural schema is equal.
  PR-9b should compare with `description` removed.
- The Temporal worker (`activities.py`, PR-11's file) ignores
  `PROXYLOOP_FAST_BACKEND`; only the API refuses it under Temporal.
