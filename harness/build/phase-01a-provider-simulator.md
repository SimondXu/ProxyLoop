# Phase 01A — Deterministic Provider Simulator Loop

**Status**: Complete

**Activation**: Explicitly approved by the user after PR #2 was squash merged on 2026-08-23. Active branch: `feat/phase-01-provider-simulator`, based on merged `main` commit `98a7514`.

**Roadmap source**: the first executable slice of Phase 1 in `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`

## Objective

Prove one synchronous, deterministic, fictional-mobile-provider success path from Case creation through an externally evidenced Completion Decision, while rejecting expired authorization, illegal offer-state transitions, and unsupported completion.

This phase is a subset gate. It does not complete the roadmap's full simulator and benchmark phase.

## Inputs

- `GOALS.md`
- `CONTEXT.md`
- `docs/architecture.md`
- `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`
- `docs/decisions/2026-08-21-monorepo.md`
- `docs/decisions/2026-08-22-contract-wire-format.md`
- canonical contracts under `runtime/packages/contracts/`
- `harness/context/phase-01a-preflight.md`

## In Scope

- one fictional postpaid-mobile Provider with one eligible lower-cost plan;
- one reproducible success scenario and fixed clock/identifier inputs;
- an in-memory offer state machine with the legal path:
  - `available -> offered -> awaiting_approval -> confirmed`;
- deterministic construction of a canonical `Case`, `ProviderOffer`, `ActionIntent`, and `ApprovalRequest`;
- exact approval binding to Case, action, strategy, constraints, material terms, offer identifier/revision, and expiry;
- Provider execution only after a current approved request;
- immutable Provider confirmation data and canonical `Evidence` derived from its content hash;
- a deterministic verifier that alone emits the canonical `CompletionDecision`;
- one CLI command that emits the complete successful episode as JSON;
- tests for:
  - the complete successful episode;
  - approval used at or after expiry;
  - an illegal offer-state transition;
  - forged or mismatched confirmation Evidence;
- repository-native format, lint, type, test, simulator, layout, lock, and contract-drift checks.

## Non-Goals

- additional scenario families, Provider configurations, personas, retention ladders, refusal branches, or stochastic behavior;
- benchmark manifests, family/entity splits, Safe Observation Adapter, scripted/oracle comparisons, trajectory generation, rewards, or data curation;
- frontend, FastAPI, PostgreSQL, Temporal, PydanticAI, model calls, model downloads, serving, or training;
- Gmail, LiveKit, telephony, browser automation, or real-provider integration;
- durable retries, process recovery, outbox storage, authentication, or production deployment;
- changes to the canonical Phase 00B wire-contract surface unless a demonstrated incompatibility blocks this phase.

## Module Ownership

```text
runtime/packages/telecom_domain/
  pure confirmation representation, canonical hashing, approval checks,
  and deterministic completion verification

runtime/packages/provider_simulator/
  fictional Provider state, legal transitions, deterministic mutation,
  success-scenario orchestration, and JSON CLI
```

`provider_simulator` depends on `telecom_domain` and canonical contracts. `telecom_domain` depends only on canonical contracts. Neither package imports a service, database, workflow, channel, model, or ML module.

## Observable Flow

```text
create Case
  -> Provider issues canonical ProviderOffer
  -> ProxyLoop builds canonical ActionIntent
  -> Provider marks the offer awaiting approval
  -> ProxyLoop builds and approves canonical ApprovalRequest
  -> Provider checks current exact approval and applies the offer
  -> Provider emits content-addressed canonical Evidence
  -> deterministic verifier emits CompletionDecision
```

## Required Invariants

1. The Provider cannot confirm an offer from any state except `awaiting_approval`.
2. Approval use requires `decision=approved` and `decided_at <= execution_time < expires_at`.
3. Intent and approval must reference the exact Case revision, strategy revision, constraint-set revision, offer identifier/revision, and material-terms hash.
4. Provider mutation is the only source of confirmation data and simulator Evidence.
5. Evidence must reference and hash the exact confirmation record used by the verifier.
6. The verifier returns `complete` only when the Case goal/required features, applied offer, current approval, confirmation, and Evidence all agree.
7. A caller-supplied Evidence identifier or model claim is insufficient for completion.
8. Running the built-in scenario twice produces semantically identical JSON.

## Build Loop

### 1. Preflight

- confirm merged `main`, active branch, canonical contract surface, and package skeletons;
- freeze the state path, approval-use rule, confirmation hash, CLI output, and deferred Phase 01B boundary.

### 2. Red

Add the smallest failing tests for the success episode, expired approval, illegal state transition, forged Evidence, and JSON CLI output.

### 3. Green

Implement only the two pure packages, deterministic scenario, and root simulator command required by those tests.

### 4. Refactor

Remove only demonstrated duplication. Do not introduce abstract Provider ports, registries, persistence interfaces, workflow adapters, or general scenario engines while only one implementation exists.

### 5. Verify

Run focused Phase 01A tests first, then the complete repository `make preflight` gate and `make simulator`. Record exact observed results in `harness/build-log.md`.

### 6. Review

A reviewer independent of the implementation must compare the complete diff and evidence against this file. The implementing agent cannot self-approve the phase.

## Acceptance Criteria

- [x] One CLI command emits a complete JSON episode using only fictional data.
- [x] The successful episode follows `available -> offered -> awaiting_approval -> confirmed`.
- [x] The emitted canonical objects bind to one Case and exact revisions consistently.
- [x] The accepted offer reduces recurring cost and retains the Case's required features.
- [x] Consequential execution requires a current exact approval.
- [x] Execution at or after approval expiry is rejected without confirmation or Evidence.
- [x] An illegal state transition is rejected without changing Provider state.
- [x] Forged or mismatched Evidence cannot produce a `complete` decision.
- [x] Completion is produced only by the deterministic verifier from Provider state and Evidence.
- [x] Repeated built-in runs produce semantically identical JSON.
- [x] Package dependency tests enforce the documented inward dependency direction.
- [x] Focused tests and the complete repository preflight pass.
- [x] No deferred Phase 01B, API, persistence, workflow, model, training, channel, or UI work enters the diff.
- [x] Exact verification evidence is appended to `harness/build-log.md`.
- [x] Independent review has no unresolved blocking findings.

## Stop Condition

Phase 01A is complete. Stop here. Do not begin Phase 01B benchmark expansion, Phase 02 data work, model experiments, product services, or UI without a new explicit user gate.
