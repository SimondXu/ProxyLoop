# Repo audit — Lane B1: decision and authority core

Reviewer: `reviewer` (Opus, high), read-only; 93 tool uses, ~234K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Reproduction scripts referenced below live under the session
scratchpad `b1/` (not in the repository) and were re-run by root.

Scope as read: `agent_core/{router,coordinator,capabilities,observation,scripted,interfaces}.py`,
`telecom_domain/{offer_policy,domain}.py`, `openai_adapter/{adapter,outputs,errors}.py`,
the contract types they use, and every test that exercises them. The
packet's `runtime/packages/agent_core/tests/**` and
`runtime/packages/openai_adapter/tests/**` do not exist; coverage lives in
`tests/integration/test_phase_03a1_agent_core.py`, `test_phase_01b_observation.py`,
`test_phase_04b_model_runtime.py`, `test_phase_01a_simulator.py`, and the
two `test_offer_policy*.py` files.

## 1. Verdict per module

| Module | Verdict | Why |
|---|---|---|
| `agent_core/capabilities.py` | refactor | Expiry/revision/binding checks are real, but the executor does not consume an approval (B1-1) and never compares approved terms to the current offer (B1-2); the "sole side-effect lane" guarantee depends on caller conventions and the simulator's state machine. |
| `agent_core/coordinator.py` | keep (small refactor) | Stale/forbidden-intent validation is real and tested with real objects; `compare_and_swap`/`_current_snapshot` are dead in the product runtime; action-proposal hash self-consistency is not checked. |
| `agent_core/router.py` | keep | Precedence matches `docs/architecture.md:180-185`; approval-decision label trust (B1-12) and terminal ignoring `completion.case_revision` are weak. |
| `agent_core/observation.py` | refactor | Default oracle is the frozen Phase 01B predicate, not the shared policy the docs claim (B1-5); duplicate `_OfferComplianceContext`; `ProviderOffer` path erases `applied_changes`. |
| `agent_core/scripted.py`, `interfaces.py` | keep | Deterministic; thin protocols. |
| `telecom_domain/offer_policy.py` | keep | Arithmetic correct at every boundary tried; one hard-coded credit constant duplicated in the simulator (B1-11). |
| `telecom_domain/domain.py` | keep | Strongest module in scope; misses `offer.case_id` (B1-8), raises instead of deciding on negative fees (B1-9). |
| `openai_adapter/outputs.py` | refactor | Runtime compiler cannot compile the only advertised capability (B1-3) and emits intents no executor or domain check can bind (B1-4); accept path untested. |
| `openai_adapter/adapter.py` | keep (minor fixes) | Fail-closed; model-prefix rule too loose (B1-6); error classification wrong for SDK-side schema failures (B1-7). |
| `openai_adapter/errors.py` | keep | — |

## 2. Findings

**B1-1 — Important (Blocking once any non-simulator capability exists)**
`capabilities.py:67-81, 231-258`. Idempotency is keyed only on
`action_intent.idempotency_key`; the approval binding never includes the
key and the executor keeps no per-approval ledger, so one APPROVED
`ApprovalRequest` authorizes unlimited executions under fresh keys.
Claim: `docs/architecture.md:243` ("executor revalidates strategy,
authority, approval, expiry, capability, and idempotency immediately before
invoking"), `:268`, `:272`.
Repro (`b1_exec_1.py`): execute with `episode.action_intent`; execute again
with the same approval and `idempotency_key="other-key"` → `first:
executed`, `second: executed`, adapter effects `2`.
Mitigation today is convention only: `case_runtime/runtime.py:1541`
hard-codes `phase-04a:{case_id}:accept-offer`, and the simulator offer
state machine refuses a second transition. Direction: record
`approval_id → evidence` in the executor and reject
`approval_already_consumed` when the same approval arrives under a
different binding; or derive the key from `approval_id`.

**B1-2 — Important**
`capabilities.py:160-161, 181-192`. The executor checks that
`intent.material_terms_hash` matches the intent's *own* terms and that
`offer_ref.offer_revision` matches, but never derives the terms from the
snapshot offer. `domain.validate_approval_use` does (`domain.py:184-187`)
and is not called by the executor.
Claim: `docs/architecture.md:272` ("A stale strategy or approval cannot
authorize a changed offer"), `:245`.
Repro (`b1_exec_3.py` case 3): a valid snapshot whose offer has
`monthly_price +100`, same `revision`, recomputed planning basis, with the
original intent/approval → `executor: executed`, effects `1`;
`validate_approval_use` on the same inputs raises `ApprovalBindingError`.
Runtime is protected only because the simulator's `prepare` calls
`validate_approval_use` (`provider_simulator/provider.py:152`) — by the
Provider, not the side-effect lane. Direction: give the executor a
terms-derivation seam and reject `current_offer_terms_mismatch`; or require
`PreparedSimulatorExecution` to carry the terms it validated and compare.

**B1-3 — Important**
`openai_adapter/outputs.py:188-191` builds `capability_id =
f"simulator.{proposed.capability}"` = `simulator.accept_offer`; the runtime
manifest advertises only `simulator.accept_fictional_offer`
(`case_runtime/runtime.py:1603`, `postgres_repository.py:1263`). Any model
output with `next_capability: accept_offer` raises `ValueError` →
`adapter.py:89-90` `INVALID_OUTPUT` → the whole `SlowWorkResult` including
the strategy is discarded; in the API this is the 503 path.
Claim: `docs/architecture.md:193`, `:122`.
Repro (`b1_outputs.py` case 1): `ThinAgentRuntime().create_case()` snapshot
→ `build_slow_request` → `compile_slow_output(...,
AcceptOfferCapabilityModelOutput(offer_position=0))` → `ValueError: Slow
output proposed an unsupported capability`. No test exercises the runtime
compiler with `next_capability` set. Direction: resolve the definition by
`allowed_action_types` or an explicit id map; add a runtime test.

**B1-4 — Important**
`outputs.py:239, 290-295`. The runtime compiler's `ActionIntent` uses 3
terms (`monthly_price/total_cost/term_months`) while the canonical terms are
the 6 from `domain.offer_material_terms` (`domain.py:123-137`); its hash is
over the unsorted list, which neither `capabilities._material_terms_hash`
(sorted, `:276-287`) nor `domain.material_terms_hash` (`:140-145`)
reproduces. Three hash functions exist for one field.
Repro (`b1_outputs.py` case 2): `intent.material_terms_hash ==
_material_terms_hash(intent)` → `False`; `== material_terms_hash(...)` →
`False`; `validate_slow_result` still returns `slow_result_current`. Any
model-compiled intent is dead on arrival at the executor
(`action_material_terms_hash_mismatch`). Latent because `case_runtime`
derives its own intent (`runtime.py:1525-1543`). Direction: one
`offer_material_terms`/`material_terms_hash` pair owned by `contracts` or
`telecom_domain`, used everywhere; delete `_material_terms` from
`outputs.py`; make `validate_slow_result` verify hash self-consistency.

**B1-5 — Important (evaluation validity; escalated to D2)**
`observation.py:351-352, 408-409, 434-454`. `ScriptedOracleConsumer()` with
no argument uses the frozen Phase 01B predicate; the shared policy runs only
when injected. Default (legacy) callers: `scripts/run_phase_03a1_harness.py:704,
1135`, `scripts/run_phase_01b_benchmark.py:131`, `fresh_fixtures.py:755`,
`artifacts_v2.py:159`, `ml/data_pipeline/.../pipeline.py:253`. Injected:
`phase03b_experiment.py:1227`, `phase03c_experiment.py:643`, the parity test.
Claim: `PLANS.md:179-183` ("one authoritative shared policy now consumes the
same explicit public inputs for Provider verification and the scripted
oracle … This result is complete").
Repro (`b1_policy.py`): understated total with undisclosed 30 000 fee →
legacy `accept_offer`, shared `decline`; total above `target×12` but below
`current×12` → legacy `accept_offer`, shared `decline`. The legacy predicate
has no fee arithmetic, no `monthly >= current` rule, and a different
total-cost rule.
Direction: make the shared policy the only path, delete
`_legacy_offer_is_valid`; D2 must determine whether legacy and shared
disagree on any of the 32 benchmark scenarios (if yes, the committed
ceiling/label artifacts are mislabelled and this becomes Blocking).

**B1-6 — Minor** `adapter.py:162-166`: prefix rule accepts `gpt-4o-mini` for requested `gpt-4o`. Fix: exact match or allowlist.

**B1-7 — Minor** `adapter.py:116-122`: everything raised inside `completions.parse()` becomes `transport`, including pydantic `ValidationError` for unknown enum / extra field. Fix: classify as `invalid_output`.

**B1-8 — Minor** `domain.py:152-202, 261-278`: `verify_completion` never checks `offer.case_id == case.case_id`. No current path; add the check.

**B1-9 — Minor** `domain.py:246-254` → `offer_policy.py:117-119`: negative fee `LineItem` raises `ValueError` inside `verify_completion` after the executor committed (`runtime.py:1265`); retry hits `REUSED` and raises again. Contract-side root cause: `LineItem.amount` / `ProviderOffer.fees` unconstrained (`contracts.py:125-128, 335-346`).

**B1-10 — Minor** `capabilities.py:105-106`: idempotency recorded only after `commit()` returns; an adapter that raises after mutating leaves no record; the retry executes again. Fix: pending marker before commit, or document `commit` as atomic.

**B1-11 — Minor** `offer_policy.py:8-10` `_KNOWN_CREDITS_MINOR = {"predefined_promotion_credit": 5_000}` and `scenarios.py:405` `total_cost -= 5_000` are two literals of one value, currency-agnostic. Same class as the `environment.py` module-global constants.

**B1-12 — Minor** `router.py:62-68, 115`: `WAIT_FOR_APPROVAL` bypassed whenever the latest event is a CONSUMER event labelled `approval_decision`, even if the approval is still PENDING and current (`test_phase_03a1_agent_core.py:844-879` demonstrates it). Reachable only via internal `append_event`; command layer restricts to `consumer_message`. Fix: key on approval state.

**Notes**
- N1 No test asserts `approval_missing`, `approval_not_approved`, `approval_expired`, `approval_material_binding_mismatch`, `approval_decision_not_current`, `delegated_authority_denied`, `action_material_terms_hash_mismatch`, `unsupported_capability`, `action_case_revision_mismatch`, `capability_offer_binding_mismatch`; only `current_offer_mismatch` and `evidence_execution_binding_mismatch` are asserted. Repros show these branches reject correctly today; nothing prevents regression.
- N2 `tests/contract/test_phase_03a1_architecture.py:88-107` asserts string presence in source; tautological.
- N3 `test_capability_executor_rechecks_authority_and_reuses_evidence` (`:628-640`) mutates the snapshot into an invalid one; the rejection is `('snapshot_integrity_invalid', 'current_offer_mismatch')`, so offer-revision binding is verified only incidentally.
- N4 Views copy only typed snapshot fields; leakage can only enter via `VisibleCaseEvent.content` or `ProviderOffer` fields the runtime/simulator populate (B2/D1).
- N5 `SafeObservationAdapter._adapt_offer` sets `applied_changes=()` for `ProviderOffer` input (`observation.py:315`); `_OfferComplianceContext` sets `target_currency=observation.currency`, so the target-currency rule is unreachable through the oracle.
- N6 Prompt (`adapter.py:127-155`): two-sentence system prompts; no schema description, domain rules, disclosure policy, or valid capability ids; the manifest the model sees says `simulator.accept_fictional_offer` while the output enum says `accept_offer` (B1-3). No safety hole; the cost is availability.
- N7 `FastModelOutput.action_intent: None` + `extra="forbid"` + `strict=True` and `CompletionClaim.status` Literal mean a Fast output cannot carry an intent, approval, or "done" claim. `validate_fast_result` does not check `completion_claim.evidence_message_ids` provenance.
- N8 `CaseCoordinator.compare_and_swap` / `_current_snapshot` unused by the runtime; dead mechanism.
- N9 `offer_policy.py:84-90`: when `target` is set, `total_cost_exceeds_current` is not evaluated; forbidden-change matching is exact-token (`remove_add_on` does not match `remove_add_on:premium_data`).
- N10 `REUSED` returns prior evidence without revalidation (replay 30 days after approval expiry → `reused`). By design; document it.
- N11 `router.py:91-94` `TERMINAL` ignores `completion_decision.case_revision`.

## 3. Test quality

| File | Tests | Assessment |
|---|---|---|
| `tests/integration/test_phase_03a1_agent_core.py` | 13 | Load-bearing for router precedence, stale Fast/Slow with real objects, forbidden Fast intent, idempotent reuse + concurrency, evidence-binding rejection, bounded-Fast template. Gaps: no authorization-reject branch of the executor (N1); offer-revision test confounded (N3); no test for B1-1 or B1-2. |
| `tests/integration/test_phase_01b_observation.py` | 20 | Load-bearing for allowlist, validation, oracle ordering — but every oracle test runs the **legacy** predicate. |
| `telecom_domain/tests/test_offer_policy.py` | 11 | Load-bearing per reason code. Missing: equal-to-target boundary, `target > current`, negative inputs. |
| `provider_simulator/tests/test_offer_policy_parity.py` | 3 | Oracle-with-policy vs environment parity on two scenarios; cannot detect B1-5. |
| `tests/integration/test_phase_01a_simulator.py` | 7 | Load-bearing adversarial completion tests. Good. |
| `tests/integration/test_phase_04b_model_runtime.py` | 19 | Load-bearing fail-closed transport/metadata/refusal, stale results through the runtime. Never sends `next_capability != None` (B1-3/4 undetectable); only `parsed=None`/`refusal` invalid-output paths (B1-7 undetectable). |
| `tests/contract/test_phase_03a1_architecture.py` | 7 | String-presence and layout; tautological for behaviour. |
| `tests/contract/test_phase_04b/01a/01b_architecture.py` | 3+2+2 | Layout checks only. |

## 4. Checks run / not run

Run: the 10 test files above → 87 passed in 1.40 s; repro scripts
`b1_exec_1..4`, `b1_policy`, `b1_domain`, `b1_outputs`, `b1_adapter`,
`b1_testcheck` (outputs quoted). Not run: `make preflight/lint/typecheck/test`
(root baseline), hosted calls, PostgreSQL/Temporal gates, `ml/tests`.

## 5. Open questions for the root orchestrator

1. B1-1 severity: does "a capability executes at most once per approval" belong to the executor (Blocking) or to `case_runtime`'s fixed key + simulator state machine (Important; B2 must confirm the key derivation cannot vary)?
2. B1-2: should the executor own terms-vs-current-offer comparison, or is Provider-side `validate_approval_use` the intended single enforcement point? If the latter, `architecture.md:243` overstates it.
3. B1-5: which `data/` artifacts were produced by the default (legacy) oracle? D2 to trace.
4. B1-3/B1-4: is the runtime Slow accept path intended to be live in model mode, or is `case_runtime` deliberately ignoring model action proposals? If the latter, the compiler should refuse `next_capability` explicitly.
5. Lane A: constrain `LineItem.amount`/`ProviderOffer.fees` non-negative (B1-9); require `completion_decision.case_revision == case.revision` in the snapshot validator (N11)?

## Root verification (2026-09-21)

Root re-ran `b1_exec_1.py`, `b1_exec_3.py`, `b1_outputs.py`, `b1_policy.py`
from the worktree; every quoted output reproduced exactly. Root read
`capabilities.py:60-82` (idempotency keyed only on the intent key),
`observation.py:345-356, 404-412` (legacy default), the eight
`ScriptedOracleConsumer(` call sites, and `PLANS.md:178-183`.

| Id | Verdict | Root note |
|---|---|---|
| B1-1 | confirmed, Important; **Blocking before Phase 06B2 or any non-simulator capability** | The product invariant is currently held by a hard-coded key in `runtime.py:1541` and the simulator's state machine, neither of which is the executor. Acceptable only while the simulator is the sole adapter. |
| B1-2 | confirmed, Important | Same pattern; enforcement lives in the Provider's `prepare`, not the side-effect lane. `architecture.md:243/272` overstate the executor. |
| B1-3 | confirmed, Important | Model-mode Slow cannot propose the only advertised capability. Together with A-4 this means "model-backed runtime" (04B) is model-backed for strategy text only, never for actions. |
| B1-4 | confirmed, Important | Three hash functions for `material_terms_hash`; runtime compiler's is incompatible with both verifiers. |
| B1-5 | confirmed, Important; **escalated to D2** — becomes Blocking if legacy and shared policy disagree on any of the 32 scenarios | `PLANS.md:179-183` claim is not supported for the evaluation call sites; only 03B/03C inject the shared policy. |
| B1-6 … B1-12 | accepted as reported | Each has a repro script under `b1/`. |
