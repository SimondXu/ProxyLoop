# Fix log: executor approval ledger and terms derivation (P0-2)

Spec: `harness/context/fix-executor-approval-ledger-preflight.md`.
Resolves audit findings B1-1 and B1-2 (Important; B1-1 Blocking before any
non-simulator capability) and adds the B1-N1 authorization-reject tests.
Branch `fix/executor-approval-ledger` from `main` @ `1ca982e`.

## What changed

- `agent_core/capabilities.py`: `TermsDerivation` seam
  (`CapabilityExecutor(adapter, *, terms_derivation=None)`); `_validate`
  compares the intent's material terms with the terms derived from the
  snapshot offer when the offer is found at the pinned revision →
  `current_offer_terms_mismatch`; a process-local approval ledger keyed by
  `approval_id` rejects a second execution of the same approval under any
  other binding or idempotency key → `approval_already_consumed`; docstring
  states both rules and that `commit` must be atomic. `agent_core` still
  imports only `contracts`.
- `case_runtime/runtime.py`: both executor construction sites inject
  `terms_derivation=offer_material_terms` (already imported).
- Tests (`tests/integration/test_phase_03a1_agent_core.py`): T1 approval
  consumed once; T2 same approval/key/binding reuses Evidence; T3 changed
  offer terms under the same revision rejected with the derivation and
  still executes without it (the default ML/scripts callers keep today's
  behaviour); T4 six parametrised authorization rejects
  (`approval_missing`, `approval_expired`,
  `approval_material_binding_mismatch`, `unsupported_capability`,
  `action_case_revision_mismatch`, `delegated_authority_denied`) built from
  real objects, each asserting exactly the named reason code and zero
  adapter side effects. T5 (through the runtime) dropped: no public
  command can alter an offer under an unchanged revision.

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| T1 | second `execute` → `EXECUTED`, adapter effects 2 (audit `b1_exec_1.py`: `second: executed`) | `REJECTED ('approval_already_consumed',)`, effects 1 |
| T3 | `TypeError: unexpected keyword 'terms_derivation'`; audit `b1_exec_3.py` case 3 `executed` | `REJECTED` incl. `current_offer_terms_mismatch`, effects 0 |
| T2, T4 | already correct on `main`, previously untested (B1-N1) | asserted |

Root re-ran `b1_exec_1.py` after the fix: `second: rejected
('approval_already_consumed',)`, `adapter effects: 1`.

## Checks

- Passed: focused suite (03A1 agent core, 04A, 04B, 01A, telecom_domain,
  provider_simulator) 110; `test_phase_03a1_agent_core.py` 22 after the
  review tightening; non-gated `tests/integration tests/contract
  runtime/packages` 316 passed / 37 gated skips; `make lint`,
  `make typecheck`, `make format-check`.
- Passed: artifact stability with unchanged ML callers — `harness-check`,
  `baselines-check`, `errata-check`, `hosted-rerun-check`,
  `validity-smoke-check`, `phase03b-experiment-check`,
  `phase03c-smoke-check`.
- Passed (Compose, torn down after): `postgres-check` 27,
  `phase05a-check` 26, `phase06b1-check` 32 — the injected derivation
  changes no runtime path other than execution rejection.
- Passed: `make preflight` on the stable diff — runtime 316 / 37 gated
  skips, ML 279, web 47, all gates valid.
- Independent review (`reviewer`, Opus): **Approve**. Adversarial probes:
  same approval + same key + different binding →
  `idempotency_key_reuse_mismatch`; 8 concurrent threads on one approval →
  1 executed, 7 `approval_already_consumed`, 1 commit; after the P0-1
  executor eviction the Provider state machine and the confirmation
  short-circuit still hold in-process at-most-once; reversed term order
  does not false-reject. Minor 3 (assert exactly the named reason code)
  applied by root. Minor 1 recorded below.

## Known limits

- A `terms_derivation` that raises propagates out of `execute()` instead of
  yielding a `REJECTED` outcome; unreachable through the runtime (the
  approval builder would have failed first on the same offer). Left as is
  to keep the reason-code vocabulary unchanged.
- The ledger's `REUSED` branch is unreachable because the idempotency map
  is consulted first; kept as specified.
- The ledger is process-local by design; cross-process at-most-once rests on
  the persisted execution claim (P0-1) and the Provider state machine.
