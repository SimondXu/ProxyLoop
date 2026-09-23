# Fix: the runtime Slow compiler resolves the accept capability through the manifest (P1 B1-3)

Bounded change under `harness/context/audit-remediation-decisions.md`
(execution order item 3; proposal §5 `openai_adapter`: "`compile_slow_output`
resolves the capability by `allowed_action_types`").
Branch `fix/manifest-capability-resolution` from `main` @ `dcc2b43`.

## Defect (observed on main)

`compile_slow_output`
(`runtime/packages/openai_adapter/src/proxyloop_openai_adapter/outputs.py`)
looks the proposed capability up by the string `f"simulator.{proposed.capability}"`.
The model vocabulary says `accept_offer`, so it looks for
`simulator.accept_offer`, but the only capability the runtime ever advertises
is `simulator.accept_fictional_offer` (`case_runtime/runtime.py` `_manifest`,
`postgres_repository.py`). Any real Slow output that proposes accepting an
offer against a runtime snapshot raises
`ValueError("Slow output proposed an unsupported capability")`, so a
model-compiled accept intent is dead on arrival. The existing test
`tests/integration/test_offer_policy_authority.py::test_compiled_slow_accept_binds_the_domain_material_terms_and_hash`
passes only because its hand-built manifest uses the ML name
`simulator.accept_offer`.

(B1-4, the second half of the original audit row, was closed by G2a #47:
`outputs.py` already uses `offer_material_terms` / `material_terms_hash`.)

## Frozen design

1. For `AcceptOfferCapabilityModelOutput`: resolve the manifest definition
   whose `allowed_action_types == (ActionType.ACCEPT_OFFER,)`. Exactly one
   such definition must exist; zero or more than one → the existing
   `ValueError("Slow output proposed an unsupported capability")`. The
   compiled `CapabilityReference` uses that definition's `capability_id` and
   `version` (already the case after lookup).
2. For `NonOfferCapabilityModelOutput`: keep the exact-id lookup
   `simulator.<name>` and the existing single-action-type and
   "not ACCEPT_OFFER" consistency check. These names have no `ActionType`
   counterpart; changing their resolution is out of scope.
3. No change to the model output schema, prompts, `ml/` (its own
   `slow_output.py` and manifests use `simulator.accept_offer` consistently),
   contracts, or the runtime manifest ids.

## Regression tests (write first)

In `tests/integration/test_offer_policy_authority.py` (or a new focused file
next to it if cleaner):

- **T1 (fails on main)**: the same compile as the existing test, but the
  request is built from a snapshot whose manifest is the runtime's
  (`simulator.accept_fictional_offer`; build it the way the runtime does or
  via `ThinAgentRuntime` snapshot) → compiles; the proposal's
  `capability_id == "simulator.accept_fictional_offer"`; the intent's action
  type is `ACCEPT_OFFER`.
- **T2**: the existing ML-named manifest (`simulator.accept_offer`) still
  compiles (existing test stays green unmodified).
- **T3**: a manifest with two definitions allowing `ACCEPT_OFFER` → raises
  `ValueError`; a manifest with none → raises `ValueError`.
- **T4**: a non-offer capability (e.g. `request_replan`) still resolves by its
  exact id when the manifest has `simulator.request_replan`, and still raises
  when absent.

## Verification

The touched test module(s), `tests/integration/test_phase_04b_model_runtime.py`,
`tests/integration/test_phase_03a1_agent_core.py`, then `make preflight-fast`.
