# Phase 03A0 — Fast/Slow Architecture Gate

**Status**: Complete; independently reviewed, passed CI/GitGuardian, and squash merged to `main` as `54afcb8` through PR #7.

**Activation**: Explicitly approved by the user on 2026-08-23 after Phase 02 was squash merged as `f45b1ea`. Implemented on `docs/phase-03a0-fast-slow-architecture` and integrated through PR #7.

**Roadmap source**: Phase 3 in `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`, narrowed to an architecture prerequisite before evaluation implementation.

## Objective

Freeze an implementable Fast/Slow orchestration contract before Qwen evaluation, model training, teacher-backed data expansion, or product-agent development. The gate must prevent either model from owning authoritative state, routing, authorization, side effects, or final completion.

## In Scope

- the deterministic Router and its mandatory Slow triggers;
- model-external shared Case-context semantics and separate Fast/Slow model views;
- Slow work request/result, planning-basis pins, event cursor, and stale-result rules;
- one serialized Case write/side-effect lane with parallel-capable model reads;
- capability-manifest, policy, approval, executor, and verifier ownership;
- the Qwen Fast training and evaluation boundary;
- Pine public-evidence boundaries and rejected architecture alternatives;
- Phase 03A1 prerequisites, evaluation matrix, and stop condition;
- repository status correction for the completed Phase 02 squash merge.

## Frozen Architecture Contract

- Fast and Slow are separate, replaceable model interfaces coordinated by a deterministic Router. They do not call one another.
- Models share structured, model-external Case state through allowlisted views; they do not share hidden chain-of-thought, KV cache, raw prompts, or free-form memory.
- The Router, not Fast confidence or prose, owns mandatory Slow scheduling and emits version-bound reason codes.
- Fast proposes only dialogue act, concise response, candidate facts, reasoner request, and completion candidate. Phase 03A1 requires `FastTurnDecision.action_intent=null`.
- Slow proposes version-bound strategy and bounded capability/action work. It does not execute tools or side effects.
- A versioned capability manifest is the only advertised capability vocabulary. Phase 03A1 exposes fictional-Provider simulator capabilities only.
- Policy, approval, capability execution, and completion verification remain deterministic authorities outside both models.
- Planning validity is bound to material state through a planning-basis fingerprint; harmless dialogue may advance the event cursor without invalidating a strategy.
- Fast and Slow may read one immutable snapshot concurrently, but one Case has a serialized write and side-effect lane.
- Stale model results are retained in Model Trace evidence, rejected without state mutation or output delivery, and rerouted on the latest snapshot.
- The text research MVP may run mandatory Slow refresh synchronously while preserving a later bounded concurrent path. Temporal and full-duplex voice are not prerequisites.
- Phase 02's 128 one-turn records remain Data Factory regression evidence, `pending_human`, and `training_ready=false`; they are not reclassified as Qwen training data.

## Non-Goals

- runtime contract, JSON Schema, generated TypeScript type, simulator, Data Factory, or product-code implementation;
- Qwen/LFM/model download, inference, prompt tuning, benchmark execution, SFT, QLoRA, RL, or teacher/model API calls;
- multi-turn dataset generation, open-data ingestion, human annotation, or training-readiness claims;
- FastAPI, PostgreSQL, Temporal, MLflow, vLLM, product Agent, frontend, browser, MCP, Gmail, LiveKit, telephony, real Provider integration, credentials, or consumer PII;
- claims that Pine's undisclosed router, state store, authorization, model identities, or training recipe are known.

## Acceptance Criteria

1. `docs/decisions/2026-08-23-fast-slow-orchestration.md` labels Pine architecture statements as public self-description and ProxyLoop's protocol as a project decision.
2. One responsibility matrix assigns sole authority for routing, turn proposals, strategy, policy, approval, execution, state, and completion without overlap.
3. The shared Case-context definition maps existing Case, constraints, Delegated Authority, Fact Ledger, Strategy Packet, offers, Action Intents, Approval Requests, Evidence, completion state, pending work, Provider reference, event cursor, and capability-manifest version.
4. Fast and Slow model views are separately allowlisted, and both exclude Provider-private/gold/evaluator fields, hidden chain-of-thought, KV cache, raw prompts, and free-form memory.
5. Routing outcomes, deterministic reason codes, mandatory Slow triggers, and precedence over advisory Fast `reasoner_request` are frozen.
6. Planning-basis semantics distinguish material strategy invalidation from non-material event-cursor movement.
7. Slow work is version-bound, echoes input pins, proposes rather than executes capabilities/actions, and cannot patch a stale Strategy Packet.
8. Phase 03A1's Qwen Fast input/output and training targets are explicit; strategy, tool planning/execution, memory, approval, Evidence verification, final completion, credentials, and workflow durability are prohibited targets.
9. The existing optional Fast `action_intent` field remains wire-compatible but is explicitly disabled (`null`) for Phase 03A1 requests and accepted outputs.
10. Parallel model reads, one serialized Case write/side-effect lane, compare-and-swap acceptance, stale-result audit/rejection, and idempotent executor Evidence are specified without requiring Temporal.
11. A capability manifest is the sole action vocabulary; the next phase exposes simulator capabilities only and does not invent MCP, email, telephony, LiveKit, or real-Provider skills.
12. Execution revalidates strategy/basis, delegated authority, approval, expiry, capability, and idempotency; deterministic Evidence verification remains the only path to `complete`.
13. Phase 03A1 is defined as multi-turn evaluation-harness and frozen-test-set implementation followed by untuned Fast/Slow baselines; training and data expansion remain separately gated.
14. Repository status documents identify Phase 02 as squash merged at `f45b1ea`, Phase 03A0 as the only active bounded phase, and later Phase 03 work as inactive.
15. No runtime source, canonical wire contract, generated schema/type, dataset artifact, dependency, lockfile, product service, or channel implementation changes in this phase.
16. A deterministic documentation gate verifies the required Phase 03A0 artifacts and frozen responsibility/routing/training-boundary statements.
17. `make preflight` passes, the complete diff receives an independent review, accepted findings are remediated, and exact evidence is appended to `harness/build-log.md`.

## Phase 03A1 Prerequisites

The next gate must implement, with deterministic local adapters and tests:

- Case-context snapshot projection and separate Fast/Slow model views;
- Router outcomes, priorities, and reason codes;
- Slow work request/result and planning-basis comparison;
- simulator-only capability manifest and executor;
- multi-turn episode/event export suitable for evaluation;
- development, held-out family/entity/provider, and safety test manifests;
- untuned Fast with Slow off/on, scripted-oracle, and frontier-reference baselines.

It must not begin training or generated-data expansion until those baselines produce failure slices.

## Stop Condition

After this documentation and architecture gate passes independent review and CI and is squash merged, stop. Phase 03A1 implementation, model calls/downloads, benchmark execution, training, data expansion, product services, channels, and UI require a new explicit user gate.
