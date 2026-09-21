# Phase 03C Stage 1a Preflight — scenario parameterisation

Date: 2026-09-21

## Activation evidence

- The user authorized the whole Phase 03C flow on 2026-09-21 ("不用咨询我 全自动
  完成所有任务") with the standing constraint that real spend and credentials
  stay separate gates; Stage 1a is USD 0 and local.
- Stage 0 merged as PR #33 (`aaae134`); `harness/status.toml` moved from
  `idle` to `in_progress`, `active_product_phase = "03C-stage1a"`.
- Branch `feat/phase-03c-stage1a-parameterisation` from `main` `aaae134`.

## Observed state (explorer evidence card + root reads)

- Every hard-coded case number lives in `scenarios.py` (`CASE_*` constants,
  `_build_scenario` literals 7_200 / 30_000 / 5_000) and, separately, in
  `episode.py::_build_case` (Phase 01A Case: 9_200 / 7_500). `ml/evaluation`
  reads everything from the scenario and Case objects.
- `environment.py::_offer_constraint_violations` builds its compliance
  context from the module-level `CASE_*` globals, not from the scenario, so
  a parameterised scenario would be verified against the wrong numbers
  unless it is changed.
- `fresh_fixtures.py` (r4-frozen) builds observations from
  `Phase01AEpisode.success().case` and asserts `== 32` on the Phase 03A1
  manifest; `splits.py` keys on `family_id`/`entity_cluster` and asserts 16
  families. Neither needs to change while the base catalogue stays 32.
- `offer_policy._KNOWN_CREDITS_MINOR` pins `predefined_promotion_credit` at
  5_000; a different promo credit is a `fee_total_mismatch`.
- Frozen catalogue fingerprint (ids, provider turns, private semantics) at
  `main` `120e102`/`aaae134`:
  `425c7afbf64a8506afca8a855f75f9ac7d3d2e124b04237efe2f1fdc46f21d1f`.

## Frozen decisions

1. `ScenarioParameters` is a frozen dataclass with arithmetic validation;
   `DEFAULT_PARAMS` equals the historical constants; `BenchmarkScenario`
   gains `parameters` with that default so every existing construction and
   the 32 frozen ids/bytes are unchanged (pinned by test).
2. A seed identifies an instance: `parameters_from_seed(seed)` is a fixed
   `random.Random("proxyloop-scenario-params-v1:<seed>")` draw sequence,
   seed 0 is the frozen default, and non-default ids carry `::p<seed>`.
   `BENCHMARK_SCENARIOS` stays the 32-row frozen catalogue;
   `build_parameterised_scenarios(seeds=...)` is a separate surface.
3. `promo_credit_minor` stays a parameter but the generator always emits
   5_000 (policy-pinned); an instance claiming another credit is quarantined
   by the `twelve_month_arithmetic` invariant. This is asserted by test.
4. `environment.py` reads the compliance context from `scenario.parameters`.
   `episode.build_case(params)` produces the parameterised Case;
   `build_case(DEFAULT_PARAMS) == Phase01AEpisode.success().case`.
5. Invariant suite, observation builder, and position harvest live in
   `ml/evaluation/.../phase03c_scenarios.py` (ML already depends on both
   runtime packages; `provider_simulator` must not import `agent_core`).
   Committed manifest `data/manifests/phase-03c-scenario-invariants.json`
   over seeds 1..1000 × 32 with a `phase03c-invariants-check` target.
6. Multi-turn positions: the Phase 03A1 environment is terminal after one
   input, so "2–3 positions" collapses to exactly 2 (opening turn; provider
   follow-up after the oracle's canonical message).
7. Message variants: three phrasings per hazard; variant 0 is the frozen
   text. Variants change only the public message.

## Decision recorded for Stage 1b (root orchestrator, 2026-09-21)

The local `.env` (git-ignored, untracked) holds a key for the OpenAI-compatible
relay `https://29qg.com/v1` that `openai_frontier.py` already targets. A
read-only `/v1/models` listing shows no "gemini flash 3.8"; the newest
Gemini flash ids there are `gemini-3.5-flash` / `gemini-3.6-flash`, and
`claude-sonnet-5`, `claude-opus-5`, `gpt-5.6-*` are also listed. Stage 1b
will therefore implement the teacher adapter on the relay seam with a
configurable model id (not an Anthropic-SDK adapter), pilot two teachers
(`gemini-3.6-flash`, `claude-sonnet-5`) within the USD 15 cap, and select by
F2. Caveats: relay model names are not verifiable as upstream models; relay
prices are not exposed, so the ledger multiplies usage by a user-maintained
rates file and is an accounted estimate. Real calls remain a separate gate.
