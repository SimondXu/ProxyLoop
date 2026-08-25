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

## Phase 03B Gate 1 closeout

- [Phase 03B Qwen3-4B controlled-smoke executable contract](../harness/build/phase-03b-qwen-qlora-smoke.md)
- [Phase 03B readiness preflight](../harness/context/phase-03b-readiness-preflight.md)
- [Phase 03B final comparison](../data/experiments/phase-03b-qlora-smoke/results/comparison.md)
- [Phase 03B final clean Terra review](../harness/code_review/phase-03b-qwen-qlora-smoke.md)

The Phase 03B contract is now closeout-only. The one frozen QLoRA training run
and one canonical Arm B evaluation are recorded as descriptive evidence. Clean
Terra returned `NO_GO_STOP_PHASE03B`, accepted by Sol, from Arm B
schema/canonical/E2E `0/6`, six invalid JSON outputs, mostly unassessable
apparent safety zeros, unsupported `4/6`, and `arm_b_hard_gates_pass=false`.
That boolean is only a necessary detector-based safety summary, not sufficient
for Go, evaluability, task quality, or promotion. No additional training, data
expansion, model rerun, promotion, deployment, or next phase is authorized.

## Original Phase 03B proposal

- [Original Qwen3-4B QLoRA readiness and comparison proposal](planning/phase-03b-qwen-qlora-experiment.md)

This planning document is retained as the original proposal and background. It
is not the current executable contract and does not independently authorize
model execution, training, downloads, external calls, or data expansion.

The telecom specification is the v1 scope. `ProxyLoop` is the platform name, not a claim that telecom, auto negotiation, or other future verticals are already implemented.
