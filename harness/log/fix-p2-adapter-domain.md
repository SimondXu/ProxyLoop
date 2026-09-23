# Fix log: P2 hygiene — adapter, verifier, executor claim, credit constant

Spec: `harness/context/fix-p2-adapter-domain-preflight.md`.
Resolves audit findings B1-6, B1-7, B1-8, B1-10, B1-11 (Minor).
Branch `fix/p2-adapter-domain` from `main` @ `5bedcce`.

## What changed

- `openai_adapter/adapter.py`: response model must equal the configured
  model or be it plus `-YYYY-MM-DD` (B1-6); a pydantic `ValidationError`
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
  way; a raise after mutation is already short-circuited by the runtime's
  `provider.confirmation` check. Evicting the executor on that reason code
  would be a `runtime.py` change and is not made here.
- B1-6: a relay that reports a model name other than the configured one or
  its dated snapshot now fails `model_metadata`.
