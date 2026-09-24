# Fix log: P2 hygiene — adapter, verifier, executor claim, credit constant

Spec: `harness/context/fix-p2-adapter-domain-preflight.md`.
Resolves audit findings B1-6, B1-7, B1-8, B1-10, B1-11 (Minor).
Branch `fix/p2-adapter-domain` from `main` @ `5bedcce`.

## What changed

- `openai_adapter/adapter.py`: response model must equal the configured
  model or be it plus `-YYYY-MM-DD` or `-YYYYMMDD` (B1-6; the 8-digit form
  added after review); a pydantic `ValidationError`
  from `completions.parse()` is `INVALID_OUTPUT`, not `TRANSPORT` (B1-7).
- `telecom_domain/domain.py`: `verify_completion` rejects
  `offer_case_mismatch` (B1-8). `verifier_version` unchanged.
- `agent_core/capabilities.py`: the idempotency key and approval are
  claimed before `commit()`; if `commit()` raises they stay claimed and a
  later request for either is `REJECTED ("execution_outcome_unknown",)`
  (B1-10). Docstring updated.
- `contracts/offer_policy.py`: `PREDEFINED_PROMOTION_CREDIT_MINOR` is the
  owner of the credit; `_KNOWN_CREDITS_MINOR` uses it (B1-11).
  `provider_simulator/scenarios.py` is frozen V1 (D1 decision 1) and is not
  edited; a test pins its `PROMOTION_CREDIT_MINOR` to the constant.

Not changed: `interfaces.py`, `runtime.py`, `repository.py`,
`postgres_repository.py`, `coordinator.py`, `scripted.py`, `ml/`, `data/`.

## Red → green

| Item | Test | Red on main | Green |
|---|---|---|---|
| B1-6 | `test_model_adapter_accepts_only_the_requested_model_or_its_dated_snapshot` (6 cases) | 4 reject cases `DID NOT RAISE` | all 6 pass |
| B1-7 | `test_model_adapter_classifies_sdk_schema_failure_as_invalid_output` | kind `transport` | `invalid_output` |
| B1-8 | `test_completion_verifier_rejects_an_offer_from_another_case` | decision `complete` | `needs_replan`, `("offer_case_mismatch",)` |
| B1-10 | `test_capability_executor_does_not_rerun_a_commit_that_raised` | retry re-ran `commit()` (second `RuntimeError`) | retry and other-key request `REJECTED ("execution_outcome_unknown",)`, one commit |
| B1-11 | `test_v1_promotion_credit_equals_the_policy_constant` | `ImportError` (no constant) | pass |

## Checks

- Passed: `make lint`, `make typecheck`, `make format-check`,
  `make preflight-fast` (after `pnpm install --frozen-lockfile`).
- Passed: `make test` — runtime 1137 passed / 46 skipped, ML 390 passed /
  1 skipped (`yaml` not installed in the ML env, pre-existing), every
  artifact gate valid (01B, 02, 03A1, 03A1-E/R/V, 03B, 03C incl. rescore,
  negotiation V2). `git status --porcelain data/` empty afterwards.
- Not run: `make postgres-check`, `make phase05a-check`,
  `make phase06b1-check` (Compose not started), `make preflight`,
  independent review.

## Known behaviour changes

- B1-10, runtime: `ThinAgentRuntime` caches one executor per case. If the
  Provider commit raises without confirming and the same process retries
  the pending claim, the cached executor now answers
  `execution_outcome_unknown` and the runtime raises `CaseConflictError`
  instead of calling `commit()` again. With the in-memory Provider a
  pre-mutation raise is deterministic, so the old retry failed the same
  way. A raise after mutation is short-circuited by the runtime's
  `provider.confirmation` check only with the in-memory repository, which
  keeps the same Provider object; PostgreSQL rebuilds the Provider from the
  pre-commit state, so a fresh process commits once. After review (root
  decision) the cached executor is kept on `execution_outcome_unknown`
  (fail closed), and the runtime raises it with its own message: "capability
  execution outcome is unknown; reconcile the Provider state before
  retrying" (same `CaseConflictError` class, no new API or Temporal
  category).
- B1-6: a relay that reports a model name other than the configured one or
  its dated snapshot (`-YYYY-MM-DD` or `-YYYYMMDD`) now fails
  `model_metadata`.

## Recorded limits (review Minor 3 and 4, not changed)

- B1-7: `parse()` validates content before `_validate_response_model` runs,
  so a swapped model that also returns schema-invalid content is recorded
  as `invalid_output`, not `model_metadata`.
- The frozen `ml/` checks keep the old prefix rule:
  `ml/evaluation/src/proxyloop_evaluation/openai_frontier.py:589` and
  `replay.py:252` (`startswith(f"{FRONTIER_MODEL}-")`). Out of scope.
- `runtime.py` binds a case's executor with `self._executors.setdefault(...)`
  to the first adapter it was built with; that binding is unchanged here.

## Update to origin/main (2026-09-24)

Merged (not rebased) `origin/main` @ `c914c1b` (#70–#73) into the branch.

- Conflict, one file: `openai_adapter/adapter.py`. Kept #70's ModelTrace
  timing (`time`/`Callable` imports, `ADAPTER_VERSION`/`PROMPT_VERSION`,
  `elapsed` measured right after `parse()` inside the `try`) and this
  branch's B1-6 `_DATED_SNAPSHOT_SUFFIX` and B1-7 `except ValidationError`
  handler, which now follows the timing line. A schema failure raises
  before `elapsed` is read, exactly as any other `parse()` failure does.
- No conflict in `capabilities.py`, `runtime.py`, or the tests. #72
  replaced the runtime's private `ExecutionClaimRecord` with the canonical
  `ExecutionClaim` 1.1 and persists model traces, but did not change how
  `_execute_claim` or `_repeat_approved` call the cached per-case
  `CapabilityExecutor`, nor the `provider.confirmation` short-circuit. The
  B1-10 runtime edge case in "Known behaviour changes" is therefore the
  same after the merge. One more path the reviewer should weigh:
  `_repeat_approved` (a command-less repeat of a terminal approval) asks the
  cached executor for `REUSED`; if that executor's commit had raised after
  mutating and the claim was then completed through the
  `provider.confirmation` short-circuit, the key is still unresolved and the
  repeat raises `CaseConflictError("approved continuation lost idempotency
  state")`. That raises before B1-10 too, because the executor had no
  record of the key; only the path to the error differs.

Checks after the merge (worktree, no `PROXYLOOP_TEST_*` set):

- Passed: `make format-check lint typecheck` (ruff format 115 + 90 files
  already formatted, ruff check "All checks passed!" ×2, mypy 66 and 59
  source files with no issues); `make preflight-fast`.
- Passed: `make test` — runtime 1184 passed / 46 skipped, ML 390 passed /
  1 skipped; every artifact gate valid. `git status --short data/` empty.
- Passed: the branch's regression tests on their own (10 passed).
- Not run: `make preflight`, `make postgres-check`, `make phase05a-check`,
  `make phase06b1-check` (the shared test DB was in use elsewhere),
  independent review.

## Review follow-up (2026-09-24)

Independent review: Approve, no Blocking or Important findings. Root
decisions applied:

- Minor 1: `runtime.py` `_execute_claim` raises `CaseConflictError("capability
  execution outcome is unknown; reconcile the Provider state before
  retrying")` when the executor answers `execution_outcome_unknown`; the
  cached executor is kept (fail closed). `capabilities.py` docstring and
  "Known behaviour changes" above corrected.
- Minor 2: B1-6 also accepts `-YYYYMMDD`.
- Minor 3 and 4: recorded under "Recorded limits" above.

Red → green:

| Item | Test | Red | Green |
|---|---|---|---|
| Minor 1 | `test_same_process_retry_after_a_raising_provider_commit_fails_closed` (`test_phase_05a_case_runtime.py`) | on the branch before the message change: message `deterministic capability execution was rejected`; with `main`'s `capabilities.py`: the retry re-ran the Provider commit (second `RuntimeError`) | `CaseConflictError` "outcome is unknown", Provider commit called once, claim still pending |
| Minor 2 | `test_model_adapter_accepts_only_the_requested_model_or_its_dated_snapshot` (11 cases; `-20240806` accepted; `-mini-20240806`, `-2024086`, `-2024-0806`, `-latest`, `-v2` rejected) | `[runtime-model-20240806-True]` failed | 11 pass |

Checks (final diff):

- Passed: `make format-check lint typecheck`; `make preflight-fast`.
- Passed: `make test` — runtime 1190 passed / 46 skipped, ML 390 passed /
  1 skipped, every artifact gate valid.
- Passed, serially, values on the command line only:
  `make postgres-check` 27 passed; `make phase05a-check` 37 passed;
  `make phase06b1-check` 34 passed.
- Passed: `make preflight` (runtime 1190 passed / 46 skipped, ML 390 /
  1 skipped, web 99 tests passed, web build compiled).
- `git status --short data/` empty.
