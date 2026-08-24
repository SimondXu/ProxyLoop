# Phase 03A1 Harness Preflight

Date: 2026-08-23

## Starting Point

- `main` commit: `54afcb8` (`docs(architecture): freeze fast/slow orchestration (#7)`);
- active branch: `feat/phase-03a1-harness`;
- starting worktree: clean and synchronized with `origin/main` before local planning files;
- merged-main `make preflight`: passed with 94 runtime/contract/integration tests, 12 ML tests, and every repository-native gate;
- Phase 02 review remains `pending_human` and `training_ready=false`.

## Observed Reusable Surface

- canonical contracts already keep Case, facts, Strategy Packet, Fast decision, approvals, Evidence, completion, and model trace typed and versioned;
- Fast decision already limits model output to bounded dialogue/facts/reasoner/completion proposals plus a backward-compatible optional Action Intent;
- Safe Observation and Scripted Oracle Consumer provide a tested leakage-safe one-turn decision seam;
- 16 Scenario Families, two Provider configurations, family/entity-safe assignments, a deterministic one-turn Provider environment, and a zero-false-completion oracle ceiling are committed Phase 01B evidence;
- the Phase 02 Data Factory supplies reproducibility, lineage, leakage, rejection, and artifact-drift patterns without model dependencies.

## Observed Implementation Gaps

- no orchestration/view/capability canonical wire models;
- no deterministic Router or deep Case coordinator implementation;
- no event cursor or material planning-basis comparison in runtime code;
- no model adapter seams, current-pin echo validation, stale result trace/rejection, or reroute;
- no simulator-only Capability Manifest/compiler/executor with current-state and idempotency checks;
- `ProviderEnvironment.apply` terminally consumes one decision, so it cannot produce a real multi-turn episode;
- existing split artifacts do not independently hold out a Provider configuration or isolate safety Families;
- no Phase 03A1 episode export, ceiling report, artifact drift command, or baseline runner;
- no ML evaluation project or model-specific dependencies.

## Root-Frozen Seams

- Sol owns canonical contract semantics, Router precedence, material planning-basis fields, capability/authorization/completion ownership, manifest eligibility, Slow-off labels, and phase completion.
- Luna implementers may implement these frozen seams in explicitly owned files but must not widen capability vocabulary or move authority into a model.
- Terra independently reviews the complete contract/runtime/simulator/evaluation diff and supplies findings; it does not approve or merge.

## Failure Attribution Boundary

No learned-model result is meaningful until the deterministic scripted oracle proves that the same public views, routing, capabilities, Provider transitions, approvals, Evidence, verifier, and manifests can produce every expected valid outcome with no false completion or leakage. The Harness gate may include expected safe non-completion outcomes; it must not relabel them as failures or completions.

## Model and External Boundary

This PR runs no model and adds no model dependency. The later Baselines PR must verify live model/runtime availability, checkpoint license, local memory/storage requirements, API credential presence outside the repository, and an explicit bounded cost estimate before calls. Those drift-prone checks are intentionally not inferred here.

## Risks for Independent Review

- optional compatibility fields could let unpinned results pass coordinator validation;
- context projection could accidentally expose private expected actions or evaluator metadata;
- planning fingerprints could omit material approval, Provider, offer, or capability changes;
- a concurrent acknowledgement route could leak material terms while strategy is stale;
- Slow proposals could be treated as authorized/executed actions;
- the multi-turn environment could merely duplicate one-turn results without real intermediate state;
- provider holdout could be nominal while the same configuration appears in development artifacts;
- idempotency could deduplicate Evidence while repeating the underlying Provider mutation;
- oracle-private access could make the environment ceiling invalid;
- phase completion could be overstated despite missing model-backed baselines, which belong to the next sequential PR.
