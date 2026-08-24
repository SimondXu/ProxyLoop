# Phase 03A1 Harness Independent Review

Date: 2026-08-23

Reviewer: independent Terra high, read-only

Final recommendation: **Approve**. No unresolved Critical or Important finding.

## Scope Reviewed

- canonical orchestration contracts and generated JSON Schema/TypeScript;
- deterministic Router, Case coordinator, immutable snapshots, CAS, stale-result handling, and Fast/Slow projections;
- simulator-only capability proposal, policy, approval, Executor, Evidence, and idempotency boundaries;
- multi-turn Provider environment and Phase 01B compatibility;
- development, family/entity-held-out, Provider-held-out, and safety manifests;
- scripted-oracle episodes, canonical ModelTrace records, ceiling report, leakage checks, and artifact drift gate;
- phase status, acceptance criteria, dependency boundary, and prohibited training/product scope.

## Initial Findings

The initial review requested changes for two Critical and five Important findings:

- formal episodes called the Provider environment directly instead of using the sole Capability Executor;
- an adapter could mutate state before returned Evidence was validated;
- episode artifacts exported per-episode oracle action, offer, and reason labels;
- Provider-held-out eligibility was nominal rather than an executable selector;
- the coordinator lacked a serialized snapshot CAS lane and strict Slow request/result binding;
- bounded Fast output relied on an English keyword filter;
- approval-decision routing trusted a caller boolean rather than the latest canonical visible event.

Minor follow-ups noted that adapter traces should use the canonical ModelTrace and that provider-facing adapters should consume public projections rather than private scenario objects.

## First Remediation

- Routed every formal capability attempt through `CapabilityExecutor`, with duplicate execution returning `reused` and one environment commit.
- Replaced mutate-then-validate with prepared Evidence plus a commit callback; Evidence case, source type, idempotency source reference, exact offer argument, approval, material terms, manifest, expiry, authority, and current snapshot integrity are validated before commit.
- Removed oracle/gold/private labels from episode artifacts and scan the complete episode export recursively.
- Added explicit development/reference-strategy eligibility selectors.
- Added serialized snapshot CAS, latest-snapshot rerouting, strict Slow request ID/revision/expiry checks, a fixed bounded Fast template, and latest-visible-event approval derivation.
- Recomputed all eight material Planning Basis components from snapshot state.

## Focused Rereview Findings

The first rereview found no Critical issue but retained two Important blockers:

- the runner recorded held-out eligibility but still sent every Provider configuration through the scripted Slow reference-strategy path;
- the Executor's idempotency `get → prepare → commit → set` sequence was not atomic across concurrent calls.

It also recommended direct mutation tests for every material Planning Basis component.

## Final Remediation

- Eligibility now controls execution before any Slow request is constructed. Only allowlisted development fixture IDs may run scripted Slow; every non-eligible/held-out episode uses the already frozen current strategy and runs Fast only.
- The ceiling gate records `reference_strategy_input_count` and requires `ineligible_reference_strategy_input_count == 0`; per-episode tests reject any non-eligible `scripted_slow` trace.
- `CapabilityExecutor` now holds an `RLock` across validation, preparation, Evidence validation, commit, and evidence registration.
- A Barrier-aligned two-thread regression with an intentionally slow commit proves one `executed`, one `reused`, and one mutation for the same idempotency key.
- Goal, constraints, Delegated Authority, verified facts, offers, approvals, Provider configuration, and Capability Manifest mutations each invalidate the Planning Basis; harmless dialogue changes only the event cursor.
- Scripted Fast/Slow traces now serialize as canonical `ModelTrace` records.

## Final Verification

Root and the independent reviewer each ran `make preflight` on the remediated worktree. Both runs passed with:

- 128 runtime/contract/integration tests;
- 12 ML tests;
- Ruff formatting and lint;
- mypy for runtime and ML;
- canonical contract generation drift and TypeScript compilation;
- Phase 01B benchmark, Phase 02 data-pilot, and Phase 03A1 Harness artifact gates;
- layout, runtime/ML lock checks, frozen offline pnpm lock, Python compilation, Docker Compose configuration, and Git diff checks.

Remote CI, GitGuardian, PR state, merge, and post-merge verification remain publication gates owned by Sol. Model quality, model cost, live provider calls, training, data expansion, and Phase 03B were not reviewed because they remain outside this Harness PR.
