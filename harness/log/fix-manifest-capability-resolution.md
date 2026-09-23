# Fix log: the runtime Slow compiler resolves the accept capability through the manifest (P1 B1-3)

Spec: `harness/context/fix-manifest-capability-resolution-preflight.md`.
Programme: `harness/context/audit-remediation-decisions.md`. Branch
`fix/manifest-capability-resolution` from `main` @ `dcc2b43`.

## What changed

- `openai_adapter/outputs.py`: `_resolve_definition` — an `accept_offer`
  proposal binds the unique manifest definition whose
  `allowed_action_types == (ACCEPT_OFFER,)`; zero or several → the existing
  "unsupported capability" `ValueError`. Non-offer capabilities keep the exact
  `simulator.<name>` lookup.
- Tests: `test_offer_policy_authority.py` T1 (runtime manifest,
  `simulator.accept_fictional_offer`), T2 (ML-named manifest still compiles),
  T3 (two / zero accept definitions raise), T4 (non-offer exact id);
  `_manifest_with` builds through `model_validate` so the manifest validator
  runs. `test_phase_04b_model_runtime.py::test_model_slow_accept_proposal_compiles_against_the_runtime_manifest`
  — public black-box: a model Slow output proposing `accept_offer` lets
  `ThinAgentRuntime.create_case()` succeed.

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| T1 | `ValueError: Slow output proposed an unsupported capability` | passes |
| T3 `[two_accept_definitions]` | `DID NOT RAISE` (exact id silently picked one) | raises |
| 04b runtime-manifest test | `OpenAICompatibleAdapterError(invalid_output)` | passes |

## Review

Independent review (`reviewer`, Opus): **Approve**, no Blocking/Important.
Probes: the compiled proposal passes the executor's `_find_capability`
against the runtime manifest; every manifest builder in the repository has
exactly one accept definition, so no wrong binding; pre-fix counterfactual
reproduced. Minors applied by root: public black-box runtime test (M1),
`model_validate` fixture (M2). Not applied: M3 (T2 duplicates existing
coverage; kept as an explicit guard).

## Known limits

- The runtime still builds its own execution proposal and ignores the
  compiled Slow capability/action proposals (`runtime.py` `_capability_proposal`);
  wiring model proposals into authority is proposal-stage work (A-4).
- The ML compiler (`ml/evaluation/.../slow_output.py:131`) still resolves by
  exact id `simulator.<name>`. Every ML manifest uses `simulator.accept_offer`,
  so it is consistent today; it would fail the same way if pointed at the
  runtime manifest. Recorded in the P2 backlog.

## Checks

See the PR body for the final `make preflight` output.
