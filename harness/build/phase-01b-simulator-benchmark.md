# Phase 01B — Simulator Breadth and Benchmark Gate

**Status**: Implementation complete; independent review passed; CI and Sol integration pending

**Activation**: Explicitly approved by the user on 2026-08-23 after Phase 01A and the Sol-governed workflow were squash merged. Active branch: `feat/phase-01b-simulator-benchmark`, based on `main` commit `c6e7b33`.

**Roadmap source**: Phase 1 in `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`

## Objective

Prove that the deterministic fictional-mobile-provider environment is broad enough and observable enough for later model attribution without leaking Provider-private or evaluator-gold data.

This phase completes the simulator benchmark gate. It does not create training trajectories or evaluate a learned model.

## In Scope

- exactly 16 versioned scenario-family definitions covering the three supported actions and refusal, clarification, expiry, fee, term, feature, disclosure, revision, and evidence hazards;
- two versioned configurations of one deterministic fictional Provider engine;
- exactly 32 benchmark scenarios, one per family/configuration pair;
- a Safe Observation Adapter in `agent_core` whose serialized model view contains only public, consumer-authorized Case and Provider fields;
- a scripted oracle consumer that makes decisions from the Safe Observation only;
- a deterministic family/entity split manifest whose grouping is stable under input reordering and keeps every family/entity derivative in one split;
- a benchmark runner and JSON CLI that report per-scenario outcomes and aggregate environment-ceiling checks;
- adversarial tests for leakage, split integrity, illegal transitions, stale or revised authorization, invalid offers, forged completion, and deterministic output;
- repository-native format, lint, type, test, benchmark, layout, lock, and contract-drift checks.

## Frozen Benchmark Contract

- Families and Provider configurations are immutable data definitions interpreted by one small engine; they are not duplicated Provider classes.
- The split unit is the connected family/entity component. Both Provider-configuration derivatives of a family stay in the same split.
- The committed manifest uses 10 train, 3 development, and 3 test family groups, with no empty split or cross-split family/entity overlap.
- The Provider-policy configuration identifier and version participate in every scenario identity and report fingerprint but are not exposed in the Safe Observation.
- The oracle may inspect only the serialized Safe Observation. It cannot inspect scenario family, entity cluster, split, hidden Provider policy, reference action, expected outcome, reward, verifier criteria, or private account/database state.
- Deterministic environment verification, not oracle self-report, decides whether each oracle decision is valid.
- The environment ceiling gate is all 32 scripted scenarios valid, zero false completions, zero leakage violations, all 16 families represented, both Provider configurations represented, and byte-stable output for identical inputs.

## Package Boundaries

```text
agent_core -> contracts
provider_simulator -> contracts + telecom_domain
benchmark composition -> agent_core + provider_simulator
```

`agent_core` owns the Safe Observation and scripted-consumer input boundary. `provider_simulator` owns scenario/configuration data, deterministic Provider transitions, split generation, and environment verification. Composition must not make the environment depend on agent-visible projections.

## Non-Goals

- normalized trajectory schemas, rollout generation, teacher/model calls, rewards, labeling, data curation, or the 100–200 trajectory pilot;
- Qwen, LFM, MLX, vLLM, SFT, RL, model download, training, or model comparison;
- FastAPI, PostgreSQL, Temporal, PydanticAI, services, persistence, retries, or production deployment;
- frontend, browser, Gmail, LiveKit, telephony, or real-Provider integration;
- stochastic personas, statistical performance claims, or public benchmark claims;
- changes to canonical Phase 00B wire contracts unless a demonstrated incompatibility blocks this phase.

## Acceptance Criteria

1. `make benchmark` emits a deterministic JSON ceiling report for 32 scenarios, 16 families, and two configurations.
2. `make benchmark-check` rejects artifact drift or any failed ceiling, leakage, split, transition, authorization, or completion invariant.
3. Safe Observation serialization contains an explicit allowlist and no benchmark labels, private Provider fields, expected actions/outcomes, rewards, or evaluator criteria.
4. Reordering scenario definitions produces the same family/entity assignments and manifest fingerprint.
5. The oracle receives no object other than Safe Observation and does not import or read scenario definitions or hidden Provider state.
6. Invalid, forbidden, expired, revised, or unsupported scenarios never count as successful completion.
7. Phase 01A's CLI and tests continue to pass unchanged.
8. `make preflight` passes, the complete diff receives independent review, accepted findings are remediated, and exact evidence is appended to `harness/build-log.md`.

## Stop Condition

After the Phase 01B pull request passes CI and Sol's final integration review and is squash merged, stop. Phase 02 data-factory work requires a new explicit user gate.
