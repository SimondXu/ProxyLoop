# Documentation index

## Product and architecture

- [Telecom bill-optimization specification](specs/2026-08-21-telecom-bill-optimization-agent.md)
- [Architecture overview](architecture.md)

## Decisions

- [Monorepo structure](decisions/2026-08-21-monorepo.md)
- [Initial implementation defaults](decisions/2026-08-22-implementation-defaults.md)
- [Fast/Slow orchestration and shared Case context](decisions/2026-08-23-fast-slow-orchestration.md)

## Planning and research

- [Initial project plan](planning/initial-project-plan.md)
- [Progress log](planning/progress.md)
- [Research foundations](research/foundations.md)

## Data

- [Phase 02 annotation guide](data/phase-02-annotation-guide.md)

## Latest evaluation evidence

- [Phase 03A1 hosted baseline reliability rerun](../harness/build/phase-03a1-hosted-rerun.md)
- [Phase 03A1 evaluation-validity smoke](../harness/build/phase-03a1-evaluation-validity-smoke.md)
- [Append-only build and verification log](../harness/build-log.md)

## Phase 04A gate

- [Phase 04A Thin Agent Runtime contract](../harness/build/phase-04a-thin-agent-runtime.md)
- [Phase 04A activation preflight](../harness/context/phase-04a-preflight.md)
- [Phase 04A independent review](../harness/code_review/phase-04a-thin-agent-runtime.md)

## Phase 04B gate

- [Completed Phase 04B Model-backed Thin Agent Runtime](../harness/build/phase-04b-model-backed-runtime.md)
- [Phase 04B activation preflight](../harness/context/phase-04b-preflight.md)
- [Phase 04B independent review](../harness/code_review/phase-04b-model-backed-runtime.md)

## Proposed next experiment

- [Phase 03B Qwen3-4B QLoRA readiness and comparison plan](planning/phase-03b-qwen-qlora-experiment.md)

The Phase 03B document is a proposed handoff, not an active implementation
gate. It authorizes no training, model download/call, data expansion, or new
evaluation artifact by itself.

The telecom specification is the v1 scope. `ProxyLoop` is the platform name, not a claim that telecom, auto negotiation, or other future verticals are already implemented.
