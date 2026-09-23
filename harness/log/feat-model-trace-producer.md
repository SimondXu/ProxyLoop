# Feat log: the ModelTrace producer (PR3: A-2)

Spec: `harness/context/feat-model-trace-producer-preflight.md`. Design:
`harness/context/schema-1.1-design.md` (PR3 row). Branch
`feat/model-trace-producer` from `main` @ `6932596` (PR2 #68). Runs in
parallel with PR4, which owns `runtime.py`, `repository.py`,
`postgres_repository.py` and `commands.py`; this slice touches none of them.

## What changed

- `agent_core/interfaces.py`: the optional traced-adapter protocol.
  - `ModelIdentity` (`provider`, `model`, `model_version`,
    `adapter_version`, `prompt_version`) and `ModelCallUsage`
    (`input_tokens`, `output_tokens`, `latency_ms | None`;
    `__post_init__` rejects negatives, non-ints and `bool`).
  - `IdentifiedAdapter` (a `model_identity` property),
    `UsageReportingFastAdapter.decide_with_usage` and
    `UsageReportingSlowAdapter.reason_with_usage`. All three are
    `runtime_checkable`; an adapter implementing none of them still works.
  - Usage is returned with the result, not stored on the adapter, so one
    adapter shared across Cases has no per-call mutable state.
- `agent_core/coordinator.py`:
  - `CaseCoordinator(..., *, clock=None, monotonic=None)`.
  - `advance` appends one 1.1 `ModelTrace` per adapter call to
    `CoordinatorOutcome.traces`, in call order (Slow before Fast on
    `fast_now_and_slow_refresh`), including rejected results. Only when
    `request.snapshot.schema_version == "1.1"`; on a 1.0 snapshot the
    adapters are called exactly as before and the injected sources are
    never read.
  - Trace fields: `role` fast/slow; `reason_codes` = the audit's reason
    codes, de-duplicated in order (see below); `input_pins` = the
    snapshot pins the call was made on; `request_id` = the Slow request
    id, `None` for Fast; `result` succeeded/rejected from the audit;
    `output_ref` = the decision or result id; `input/output_schema_version`
    from the view/request and decision/result; `safety_flags` = `()`.
  - `trace_id` is derived from every other field of the trace, including
    latency and tokens, so no wall clock or random source is read. It is
    therefore **not an idempotency key for real model calls**: a retried
    call with a different latency gets a new id. Deduplication is by
    command, not by trace.
  - Reported usage and identity are normalised, never trusted: a count
    that is not a non-negative `int` (or is a `bool`) becomes 0, an unusable
    identity field falls back to `unidentified` / the class name /
    `unversioned`. Trace building runs after the model call and must not
    turn a trace problem into a failed business call.
  - The `traces` comment on `CoordinatorOutcome` now describes the producer.
- `agent_core/scripted.py`: both scripted adapters expose
  `model_identity` (`provider="scripted"`, `scripted_fast`/`scripted_slow`,
  `deterministic-v1`, `scripted-v1`, `no-prompt`). They report no usage, so
  their traces carry zero tokens.
- `agent_core/__init__.py`: exports the five new names.
- `openai_adapter/adapter.py`:
  - `model_identity`: `provider` = the host of `base_url` (never the
    userinfo or path), `model` and `model_version` = the configured model,
    `ADAPTER_VERSION` / `PROMPT_VERSION` module constants.
  - `decide_with_usage` / `reason_with_usage` return the result plus
    `ModelCallUsage`; `decide` / `reason` delegate to them unchanged.
  - Tokens come from `response.usage.prompt_tokens` / `completion_tokens`
    when present and non-negative integers, else zero. Latency is measured
    around `completions.parse` only, with an injectable `monotonic`
    (default `time.perf_counter`).
- New `tests/integration/test_model_trace_producer.py` (11 tests).

## Timing semantics (assumption, not in the spec text)

The spec fixes "injected clock, injected monotonic source, no wall-clock
reads inside the coordinator" but not the behaviour when nothing is
injected. `runtime.py` (PR4-owned) constructs `CaseCoordinator(snapshot=...)`
without either, so the default decides what PR4 will persist:

- measured latency: the adapter-reported `latency_ms`, else the
  coordinator's `monotonic` measurement;
- no `clock`: `started_at = request.created_at` (the runtime's own clock
  value for the event) and `completed_at = started_at + latency`, latency 0
  when nothing measured the call;
- a `clock` but no measurement: `latency_ms` is the clock window's width;
- both: the clock window and the measured latency, each as injected.

The window and the latency never contradict each other when only one
source is injected (review M1). An injected clock that returns a naive or
non-UTC datetime, or a non-finite monotonic reading, is refused with a
clear `ValueError` at the first read, before the model call. An unusable
reading after the call falls back to the derived window instead of
raising (review M2).

So, until PR4 or a later change passes `clock=`/`monotonic=`, runtime
traces of the scripted adapters record latency 0 and a zero-width window;
OpenAI traces carry the adapter's own measured latency and a window of
that width.

## Red → green

- Red, on `6932596` sources with the new test file: 11 failed. Ten raised
  `TypeError` (`CaseCoordinator` / `OpenAICompatibleAdapter` do not accept
  `clock` / `monotonic`); the runtime scan failed with
  `assert set() == {'fast', 'slow'}` (no trace produced).
- Green: 11 passed.

| Acceptance | Test |
|---|---|
| One trace with the right `role` per call: Fast only, Slow only, Fast + Slow refresh; ids, pins, `request_id`, `output_ref`, JSON round-trip | `test_one_trace_with_its_role_per_adapter_call[fast_now, slow_refresh, fast_now_and_slow_refresh]` |
| Rejected results traced (`rejected`, reason codes present), Slow and Fast | `test_a_rejected_result_is_traced_with_its_reason_codes` |
| A reason repeated per offending action proposal is recorded once (the contract forbids duplicate reason codes; without this the runtime would raise) | `test_a_repeated_audit_reason_is_traced_once` |
| None for a 1.0 snapshot; injected sources not read | `test_a_1_0_snapshot_emits_no_trace` |
| No trace without an adapter call (Slow unavailable; stale request rerouted) | `test_routes_without_an_adapter_call_emit_no_trace` |
| Deterministic timestamps and latency from the injected clock and monotonic source | `test_timestamps_and_latency_come_from_the_injected_sources` |
| Without injected sources the trace is deterministic (identical on rerun) | `test_without_injected_sources_the_trace_is_deterministic` |
| Tokens from a fake `response.usage`; missing usage → zero; provider/model from config; no API key in the trace; adapter-measured latency | `test_openai_tokens_come_from_response_usage` |
| No trace id (nor a `trace_id` key) in the snapshot, Fast view, Slow request/view, or `_result_payload`, with traces captured from a real runtime flow | `test_no_trace_id_reaches_the_snapshot_views_or_browser_payload` |

Added after review (20 more test cases, 31 in total):

| Finding | Test |
|---|---|
| M1: monotonic without a clock → `completed_at = started_at + latency` | `test_a_monotonic_source_without_a_clock_derives_the_window` |
| M1: a clock without a measurement → latency = window width | `test_a_clock_without_a_measurement_uses_the_window_width` |
| M2: an adapter reporting `input_tokens=-1` (and `bool` / `str` values) still returns its decision; the trace records 0 | `test_bad_reported_usage_never_fails_the_call` |
| M2: `ModelCallUsage` rejects negatives, floats and `bool` | `test_model_call_usage_rejects_non_counts[5 cases]` |
| M2: a naive or non-UTC clock is refused before the adapter is called | `test_a_non_utc_clock_is_refused_before_the_model_call[2 cases]` |
| M3: `base_url` with userinfo, port, path and query → provider is the lowercased host only; no userinfo, port, path, query or API key in the trace | `test_the_provider_is_only_the_host_and_no_secret_reaches_the_trace` |
| M3: `_token_count` of `bool`/negative/`str`/`float`/`None` → 0, int kept | `test_token_count_accepts_only_non_negative_ints[7 cases]` |
| M3: the `provider="unidentified"` fallback | `test_an_unidentified_adapter_is_named_by_its_class` |
| M3: an adapter that raises → no trace; the same exception object propagates | `test_an_adapter_that_raises_leaves_no_trace_and_propagates` |

The OpenAI usage test now also asserts the derived window equals the
adapter-measured latency.

## Existing tests

No existing test needed an edit. The runtime suite went from 1108 to 1139
passed (the 31 new test cases).

## Review

Independent review (`reviewer`): **Approve**, with four findings, all
applied in this branch:

1. M1, half-injection produced contradictory traces (a clock window with
   latency 0, or a latency with a zero-width window). Fixed: see Timing
   semantics.
2. M2, observability could fail a business call (bad reported usage or a
   non-UTC clock surfaced as a pydantic error after the model call). Fixed:
   `ModelCallUsage.__post_init__` validation; the coordinator normalises
   usage and identity; the clock is checked before the call.
3. M3, missing tests: URL secrets, `_token_count` edge values, the
   `unidentified` fallback, a raising adapter. Added.
4. M4, note only: `trace_id` is not an idempotency key (recorded under
   What changed).

## Checks (on `6932596`, after the review fixes)

| Check | Result |
|---|---|
| `tests/integration/test_model_trace_producer.py` | 31 passed |
| runtime unit suite (inside `make test`) | 1139 passed, 46 skipped (DB/Temporal-gated) |
| `make lint` | pass |
| `make typecheck` | pass (63 + 59 files) |
| `make format-check` | pass |
| `make preflight-fast` | exit 0 |
| `make test` | exit 0: runtime 1139 passed, 46 skipped; ml 388 passed, 1 skipped |
| hosted-rescore-check | r4 execution contract unchanged `6b50437f…`; rescored artifact equals derivation |
| validity-smoke-check / harness-check | valid |
| phase03c-prompt-set-check / phase03c-rescore-check | consistent; 0 cloud disagreements |
| `git status --porcelain data/` | empty |

The drift lines `drifted_since_r1`, `drifted_since_03b` and
`drifted_since_bundle` are the pre-existing informational states recorded
on `main`. `pnpm install --frozen-lockfile` was run first so the contracts
`tsc` / `json2ts` checks inside the runtime suite could run.

Not run: `make preflight` and the Compose gates (`postgres-check`,
`phase05a-check`, `phase06b1-check`); the root runs them. No
`PROXYLOOP_TEST_*` variable was set.

## Known limits

- A model call that raises produces no trace (as the design records). On
  `fast_now_and_slow_refresh`, a Fast call that raises also loses the Slow
  trace already built, because the exception propagates out of `advance`.
- Rejected-result traces reach `CoordinatorOutcome.traces`, but the runtime
  raises before any write on a rejected result, so even after PR4 they are
  not persisted on that path (backlog R-12, proposal stage 1).
- Latency 0 and a zero-width window are recorded when nothing measured the
  call (see Timing semantics); the contract has no "unknown" value.
- An injected clock or monotonic callable that itself raises after the
  model call still propagates; only unusable return values are absorbed.
- `model_version` for the OpenAI adapter is the configured model id, not
  the served `response.model` snapshot id.
- `ADAPTER_VERSION` / `PROMPT_VERSION` are hand-maintained labels; a prompt
  edit in `_messages` must bump `PROMPT_VERSION`.
- An adapter without `model_identity` is traced as
  `provider="unidentified"`, `model=<class name>`, versions `unversioned`.
- Nothing is persisted here; PR4 appends `outcome.traces` to runtime state.

## Root gate (2026-09-23)

Final diff, run serially with the Compose profiles up and
`PROXYLOOP_TEST_DATABASE_URL` / `PROXYLOOP_TEST_TEMPORAL_ADDRESS` set:
`make preflight` exit 0 (runtime 1185 passed incl. DB-gated tests; ML and
web green; evidence gates unchanged); `postgres-check` 27,
`phase05a-check` 36, `phase06b1-check` 34 — all passed.
