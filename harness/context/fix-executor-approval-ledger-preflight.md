# Fix: executor approval ledger and terms derivation (P0-2)

Bounded repository change approved by the user on 2026-09-21 (Group 1).
Branch `fix/executor-approval-ledger` from `main` @ `1ca982e` (after P0-1,
PR #38, merged). Resolves audit findings
**B1-1** and **B1-2** (Important; B1-1 Blocking before any non-simulator
capability) and adds the missing authorization-reject tests from **B1-N1**.
See `harness/code_review/repo-audit-B1.md` and
`docs/research/2026-09-21-repository-audit.md` §6 P0 row 2.

## Defects (observed on main)

- B1-1: `CapabilityExecutor` keys idempotency only on
  `action_intent.idempotency_key` (`capabilities.py:67-81`); one APPROVED
  `ApprovalRequest` authorizes unlimited executions under fresh keys.
  Today the product is protected only by a hard-coded key in
  `case_runtime/runtime.py` and by the simulator's state machine.
- B1-2: the executor checks `intent.material_terms_hash` against the
  intent's own terms and the offer revision (`capabilities.py:160-161,
  181-192`) but never derives the terms from the snapshot offer; an offer
  whose price changed with the same `revision` still executes. Only the
  Provider's `prepare` (`provider_simulator/provider.py:152`) catches it.

## Frozen design

`agent_core` must not import `telecom_domain` (same rule as the oracle's
`offer_policy` seam, `observation.py:345-349`). Both fixes live in
`runtime/packages/agent_core/src/proxyloop_agent_core/capabilities.py`.

1. **Terms-derivation seam.**
   ```python
   TermsDerivation = Callable[[ProviderOffer], tuple[MaterialTerm, ...]]

   class CapabilityExecutor:
       def __init__(
           self,
           adapter: SimulatorCapabilityAdapter,
           *,
           terms_derivation: TermsDerivation | None = None,
       ) -> None: ...
   ```
   In `_validate` (make it an instance method or pass the callable), after
   the existing `current_offer_mismatch` / `current_offer_expired` checks and
   only when the offer was found with the matching revision: if
   `terms_derivation is not None`, compute `derived =
   terms_derivation(offer)`; if `tuple(sorted(intent.material_terms, key=lambda t: (t.name, t.value)))
   != tuple(sorted(derived, ...))` → reason `current_offer_terms_mismatch`.
   Compare the sorted `(name, value)` pairs; do not compare hashes (the
   three hash functions are unified in P0-7).
   `case_runtime/runtime.py` injects `terms_derivation=offer_material_terms`
   (from `proxyloop_telecom_domain.domain`) at both `CapabilityExecutor(`
   construction sites (the `setdefault` and the P0-1 eviction rebuild).
   `ml/evaluation` and `scripts/` callers keep the default `None` so every
   committed artifact check stays byte-identical.

2. **Approval ledger.** New process-local map
   `self._consumed_approvals: dict[UUID, tuple[str, Evidence]]` keyed by
   `approval.approval_id`, written next to
   `_evidence_by_idempotency_key` after `commit()`. In `_execute_serialized`,
   before `_validate`: if `request.approval is not None` and its
   `approval_id` is in the ledger → if the recorded binding equals
   `_request_binding(request)` **and** the idempotency key equals the
   recorded evidence's `source_ref` → `REUSED` with that evidence; otherwise
   `REJECTED ("approval_already_consumed",)`. The idempotency-key map keeps
   its current semantics (`idempotency_key_reuse_mismatch` first if the key
   was seen with another binding).
   Durability of the ledger is not this change's job: the persisted
   execution claim (P0-1) and the Provider state machine own cross-process
   at-most-once; this ledger closes the in-process hole the docs claim the
   executor closes (`docs/architecture.md:243, 268, 272`).

3. Docstring of `CapabilityExecutor` states both rules and that `commit`
   must be atomic (B1-10 stays open; note only).

## Out of scope

`telecom_domain` (no change; `offer_material_terms` already exists),
`contracts.py`, hash unification (P0-7), `case_runtime` beyond the two
injection sites, `ml/`, `scripts/`, docs other than this file.

## Regression tests (write first; each must fail on the pre-fix code)

All in `tests/integration/test_phase_03a1_agent_core.py` (the existing home
of executor tests; reuse its fixtures/episode builders):

- **T1** same approval, second `execute` with a different
  `idempotency_key` and otherwise identical request → `REJECTED
  ("approval_already_consumed",)`; adapter side effects remain 1. (From
  audit repro `b1_exec_1.py`.)
- **T2** same approval, same key, same binding → `REUSED` with the same
  Evidence (unchanged behaviour, now asserted explicitly).
- **T3** a valid snapshot whose offer has `monthly_price + 100`, same
  `revision`, recomputed planning basis, `source_pins` = new pins, original
  intent/approval, executor built with
  `terms_derivation=offer_material_terms` → `REJECTED` containing
  `current_offer_terms_mismatch`; adapter side effects 0. (From
  `b1_exec_3.py` case 3.) The same request with `terms_derivation=None`
  keeps today's outcome (executes) — assert that too, so the seam's
  default is explicit.
- **T4** parametrized authorization rejects, one case each, each asserting
  the reason code and zero adapter side effects: `approval_missing`
  (intent requires approval, `approval=None`), `approval_expired`,
  `approval_material_binding_mismatch` (approval's `material_terms_hash`
  differs), `unsupported_capability` (capability id not in the manifest),
  `action_case_revision_mismatch`, `delegated_authority_denied`. Use real
  objects built from the existing fixture, never mocks of the validator.
- **T5** `tests/integration/test_phase_04a_agent_runtime.py`: through the
  runtime (which now injects the derivation), an approved offer whose
  snapshot offer terms were altered with the same revision before
  execution is rejected with 409 and no Provider commit. If the runtime
  cannot produce that state through public commands, say so and drop T5
  with a note (the unit test T3 is the load-bearing one).

## Verification

Focused: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q tests/integration/test_phase_03a1_agent_core.py tests/integration/test_phase_04a_agent_runtime.py tests/integration/test_phase_04b_model_runtime.py tests/integration/test_phase_01a_simulator.py runtime/packages/telecom_domain/tests runtime/packages/provider_simulator/tests`
Artifact stability (ML callers unchanged): `make harness-check baselines-check errata-check hosted-rerun-check validity-smoke-check phase03b-experiment-check phase03c-smoke-check`
Gated: `make postgres-check`, `make phase05a-check`, `make phase06b1-check`
(Compose as in the P0-1 spec; tear down after). Static: `make lint`,
`make typecheck`, `make format-check`. Root runs `make preflight` once.

## Escalate instead of deciding

Any need to import `telecom_domain` from `agent_core`; any change to the
`SimulatorCapabilityAdapter` protocol, `PreparedSimulatorExecution`, the
reason-code vocabulary beyond the two new codes, or an ML artifact check
that stops passing.
