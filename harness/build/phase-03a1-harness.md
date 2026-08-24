# Phase 03A1-H — Deterministic Multi-Turn Evaluation Harness

**Status**: Complete; squash merged as `e08c9b6` through PR #8.

**Activation**: Explicitly approved by the user on 2026-08-23 after Phase 03A0 was squash merged as `54afcb8`. Active branch: `feat/phase-03a1-harness`.

**Parent roadmap phase**: Phase 03A1, split into a deterministic Harness PR followed sequentially by a separately gated model-backed Baselines PR.

## Objective

Implement the smallest reproducible Agent slice that can attribute later baseline failures to model behavior rather than missing routing, state, capabilities, authorization, verification, or simulator behavior. The Harness must run entirely with deterministic local adapters before any Qwen/frontier model dependency, download, or call.

## In Scope

- canonical, versioned orchestration and model-view contracts;
- deterministic Router precedence and reason codes;
- immutable Case Context Snapshot projection and separate Fast/Slow allowlists;
- one deep Case coordinator with injected deterministic model/capability adapters;
- planning-basis fingerprinting, input pins, compare-and-swap acceptance, stale-result traces, and one serialized Case write/side-effect lane;
- simulator-only Capability Manifest, current-state policy checks, approval binding, idempotent execution, immutable Evidence, and deterministic completion verification;
- a new versioned multi-turn Provider engine that preserves the Phase 01B one-turn regression interface;
- complete public episode/event export with no private/gold/evaluator leakage;
- frozen development, family/entity-held-out, provider-held-out, and safety manifests with content fingerprints;
- a scripted-oracle ceiling report and repository artifact-drift command;
- precise Slow-off/reference-strategy semantics for the next Baselines PR.

## Non-Goals

- Qwen/LFM/frontier dependency, checkpoint download, inference, API/model call, prompt tuning, or benchmark result;
- SFT, QLoRA, DPO, RL, teacher-backed generation, public-data ingestion, project-data expansion, or training-readiness claim;
- FastAPI, PostgreSQL, Temporal, MLflow server, vLLM, product Agent service, UI, MCP, email, voice, telephony, or real Provider integration;
- credentials, consumer PII, production reliability, deployment, or release publication;
- changing Phase 02 records from `pending_human` or `training_ready=false`.

## Frozen Contract Decisions

1. Canonical wire models add `ModelInputPins`, `PlanningBasis`, `VisibleCaseEvent`, `CapabilityManifest`, `CaseContextSnapshot`, `FastModelView`, `SlowReasonerView`, `RoutingDecision`, `SlowWorkRequest`, and `SlowWorkResult` plus the minimal nested proposal/reference types they require.
2. Planning Basis includes material goal, constraints, Delegated Authority, verified facts, material offers, approval state, Provider configuration, and Capability Manifest state. Event cursor alone never determines strategy validity.
3. Existing `StrategyPacket`, `FastTurnDecision`, and `ModelTrace` remain wire-compatible. Phase 03A1 acceptance requires explicit current pins and `FastTurnDecision.action_intent=null`; compatibility defaults do not weaken coordinator validation.
4. The Case coordinator exposes one external interface that advances an immutable snapshot from one triggering event. Router, view projection, result validation, stale rejection, and deterministic handoff stay behind that interface.
5. Fast and Slow adapters are injected seams. Deterministic scripted adapters and later Qwen/frontier adapters consume the same allowlisted views and return the same typed outputs.
6. The Router evaluates exactly `terminal → verify_only → wait_for_approval → slow_refresh → fast_now_and_slow_refresh → fast_now` and emits one outcome with deterministic reason codes and current pins.
7. `fast_now_and_slow_refresh` may emit only bounded acknowledgement, clarification, or status text that contains no material terms, offer acceptance, protected disclosure, completion claim, or side effect.
8. Model results that do not echo current Case, constraint, Fact Ledger, strategy, planning-basis, event-cursor, Provider, and capability pins are traced as stale/rejected and cannot be delivered, merged, compiled, or executed.
9. A versioned Capability Manifest is the sole action vocabulary. This PR contains fictional-Provider simulator capabilities only; neither model executes them.
10. The executor revalidates current planning basis, Delegated Authority, approval, offer/material terms, expiry, manifest membership, and idempotency immediately before execution. Duplicate execution returns the original immutable Evidence without repeating the Provider mutation.
11. Deterministic Evidence verification remains the only path to `complete`.
12. Public model views and episode exports exclude Provider-private scenario policy, expected actions/outcomes, private reason codes, rewards, evaluator criteria, gold labels, hidden chain-of-thought, KV cache, raw prompts, and free-form model memory.

## Multi-Turn and Manifest Contract

- Phase 01B `ProviderEnvironment` behavior and committed artifacts remain unchanged.
- A separate `MultiTurnProviderEnvironment` starts with a public opening turn, accepts a bounded consumer message/capability, emits at least one later Provider turn, and reaches a verified terminal or safe non-completion outcome only through deterministic transitions.
- Every exported episode contains at least two visible Provider/consumer event positions, monotonic event cursors, routing decisions, accepted/rejected model traces, capability attempts, Evidence references, verification outcomes, and reproducibility fingerprints.
- The Phase 03A1 manifest assigns Scenario Family and Entity Cluster atomically and records Provider configuration assignments independently. A Provider-held-out configuration cannot appear in development/reference-strategy inputs.
- Safety cases are a separate, immutable suite excluded from future training eligibility. Every derivative of a safety Family/Entity remains safety-only.
- Manifest and report fingerprints bind schema, simulator, Router, capability, scenario-family, entity, Provider-configuration, prompt/adapter fixture, and seed versions.

## Harness Validity Gate

The scripted oracle is environment evidence, not a learned baseline. The Harness gate requires:

- 100% schema-valid deterministic adapter outputs;
- 100% Router outcome/reason-code agreement over all precedence and mandatory-Slow fixtures;
- 100% valid scripted-oracle episode outcomes;
- zero false completions, unauthorized capability executions, approval/material-term mismatches, private-field leaks, cross-split family/entity/provider violations, and duplicate Provider mutations;
- explicit rejection/audit of stale Fast, stale Slow, forbidden Fast Action Intent, unsupported capability, forged Evidence, missing Evidence, expired approval, and changed-offer approval;
- deterministic repeated generation of manifests, episode exports, ceiling report, and report fingerprints.

Harness validity does not require every episode to end in `complete`; safe refusal, clarification, escalation, needs-user, and needs-replan outcomes are valid when expected and correctly verified.

## Slow-Off Semantics Prepared for 03A1-B

- **Fast policy isolation** uses one frozen reference Strategy Packet generated only from the allowlisted Slow view by the scripted adapter. It measures the untuned Fast Model under a valid strategy and is labeled `untuned_fast_reference_strategy`, not a complete no-Slow Agent.
- **End-to-end Slow-off ablation** does not inject or silently synthesize strategy. Mandatory Slow work with no adapter produces a typed `slow_unavailable` non-completion failure; Fast cannot bypass the Router.
- **Fast+Slow baseline** uses the same Router, views, manifests, capabilities, verifier, and episode runner with Qwen Fast plus the frontier Slow adapter.
- **Frontier reference** satisfies both typed model seams with the frozen frontier configuration while retaining deterministic policy/execution/completion authority outside the model.

## Acceptance Criteria

1. Repository status records Phase 03A0 complete at `54afcb8`, Phase 03A1-H as the sole active gate, and Phase 03A1-B/03B as inactive.
2. New canonical models generate matching JSON Schema and TypeScript artifacts and reject invalid pins, references, duplicates, time order, or non-simulator capabilities.
3. Fast/Slow views are explicit allowlists and deterministic leakage probes reject nested private/gold/evaluator fields.
4. Router unit tests cover all six outcomes, overlapping-condition precedence, mandatory Slow triggers, and advisory Fast reasoner requests.
5. Planning-basis tests prove material goal/constraint/authority/fact/offer/approval/Provider/capability changes invalidate work while harmless dialogue only advances the event cursor.
6. Coordinator tests prove current output acceptance, stale Fast/Slow audit rejection, rerouting on the latest snapshot, serialized writes, and forbidden Fast Action Intent rejection.
7. Capability tests prove manifest-only proposals, authorization and approval checks, exact offer/material-term binding, expiry checks, Evidence ownership, and idempotent duplicate handling.
8. Multi-turn tests prove legal transitions, at least two visible turns, monotonic cursors, no caller-supplied Evidence authority, and preservation of all Phase 01B behavior/artifacts.
9. Frozen manifest tests prove family/entity atomicity, independent provider holdout, safety isolation, deterministic assignments, and fingerprint drift.
10. Scripted-oracle artifact gate meets every Harness Validity Gate condition and reports observed non-completion outcomes honestly.
11. Make targets generate and check the Phase 03A1 manifest, episode export, and ceiling report; `make preflight` runs the check.
12. Runtime dependency files contain no Qwen, MLX, Transformers, OpenAI, PydanticAI, vLLM, or model-serving dependency.
13. Phase 02 remains `pending_human`, `training_ready=false`, and is not consumed as model training data.
14. No model call/download, training, data expansion, product service, channel, UI, credential, PII, deployment, or Phase 03B work occurs.
15. Focused checks and `make preflight` pass, the complete diff receives independent Terra review, accepted findings are remediated, and exact evidence is appended to `harness/build-log.md`.

## Stop Condition

After independent review, repository checks, CI/GitGuardian, and squash merge, stop and inspect the merged Harness evidence. Phase 03A1-B begins on a new branch only if the Harness validity gate passes. Training, data expansion, and Phase 03B remain separately user-gated regardless of baseline results.
