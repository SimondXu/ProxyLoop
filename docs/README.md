# Documentation index

Live authorization state is [`harness/status.toml`](../harness/status.toml);
the phase index with gate artifacts is [`PLANS.md`](../PLANS.md); the
chronological delivery record is the [progress log](planning/progress.md).

## Product and architecture

- [Telecom bill-optimization specification](specs/2026-08-21-telecom-bill-optimization-agent.md) — v1 product and ML requirements; its delivery-plan numbering is superseded by `PLANS.md`
- [Architecture overview](architecture.md)
- [Development guide](development.md) — environments, Make targets, CI, Runtime modes, phase-gated workflow
- [ML evidence](ml-evidence.md) — what the evaluation and post-training results do and do not show
- [Limitations and negative results](limitations.md) — everything not done, the negative results, the recorded limits, and the cost record
- [Phase 07A portfolio demo narrative](portfolio-demo.md)
- [Local Web demo UI notes](ui/README.md), [state matrix](ui/state-matrix.md), [conversation flow](ui/user-flows.md), [UI research boundary](ui/research.md)

## Decisions

- [Monorepo structure](decisions/2026-08-21-monorepo.md)
- [Contract wire format](decisions/2026-08-22-contract-wire-format.md)
- [Initial implementation defaults](decisions/2026-08-22-implementation-defaults.md)
- [Fast/Slow orchestration and shared Case context](decisions/2026-08-23-fast-slow-orchestration.md)

## Planning and research

- [Initial project plan](planning/initial-project-plan.md) (2026-08-21 planning record)
- [Progress log](planning/progress.md)
- [Research foundations](research/foundations.md)
- [Phase 03B post-training review (2026-09-21)](research/2026-09-21-phase-03b-post-training-review.md) — why the QLoRA smoke was inconclusive and how a distillation redo should be run

## Data

- [Phase 02 annotation guide](data/phase-02-annotation-guide.md)

## Completed phase gates

Each row links the executable contract, activation preflight, independent
review, and execution log where they exist. Earlier phases log to the
historical [`harness/build-log.md`](../harness/build-log.md).

| Phase | Contract | Preflight | Review | Log |
|---|---|---|---|---|
| 00B Contracts | [contract](../harness/build/phase-00b-contracts.md) | [preflight](../harness/context/phase-00b-preflight.md) | [review](../harness/code_review/phase-00b.md) | build-log |
| 01A Provider simulator | [contract](../harness/build/phase-01a-provider-simulator.md) | [preflight](../harness/context/phase-01a-preflight.md) | [review](../harness/code_review/phase-01a.md) | build-log |
| 01B Simulator benchmark | [contract](../harness/build/phase-01b-simulator-benchmark.md) | [preflight](../harness/context/phase-01b-preflight.md) | [review](../harness/code_review/phase-01b.md) | build-log |
| 02 Data factory | [contract](../harness/build/phase-02-data-factory.md) | [preflight](../harness/context/phase-02-preflight.md) | [review](../harness/code_review/phase-02.md) | build-log |
| 03A0 Fast/Slow architecture | [contract](../harness/build/phase-03a0-fast-slow-architecture.md) | [preflight](../harness/context/phase-03a0-preflight.md) | [review](../harness/code_review/phase-03a0.md) | build-log |
| 03A1-H Evaluation Harness | [contract](../harness/build/phase-03a1-harness.md) | [preflight](../harness/context/phase-03a1-preflight.md) | [review](../harness/code_review/phase-03a1-harness.md) | build-log |
| 03A1-B Untuned baselines | [contract](../harness/build/phase-03a1-baselines.md) | [preflight](../harness/context/phase-03a1-baselines-preflight.md) | [review](../harness/code_review/phase-03a1-baselines.md) | build-log |
| 03A1-E Evaluation erratum | [contract](../harness/build/phase-03a1-evaluation-erratum.md) | [preflight](../harness/context/phase-03a1-evaluation-erratum-preflight.md) | [review](../harness/code_review/phase-03a1-evaluation-erratum.md) | build-log |
| 03A1-R Hosted rerun | [contract](../harness/build/phase-03a1-hosted-rerun.md) | [preflight](../harness/context/phase-03a1-hosted-rerun-preflight.md) | [review](../harness/code_review/phase-03a1-hosted-rerun.md) | build-log |
| 03A1-V Validity smoke | [contract](../harness/build/phase-03a1-evaluation-validity-smoke.md) | [preflight](../harness/context/phase-03a1-evaluation-validity-smoke-preflight.md) | [closeout](../harness/code_review/phase-03a1-rv-closeout.md) | build-log |
| 03B QLoRA smoke (`NO_GO_STOP_PHASE03B`) | [contract](../harness/build/phase-03b-qwen-qlora-smoke.md) | [preflight](../harness/context/phase-03b-readiness-preflight.md) | [review](../harness/code_review/phase-03b-qwen-qlora-smoke.md) · [comparison](../data/experiments/phase-03b-qlora-smoke/results/comparison.md) | build-log |
| 04A Thin Agent Runtime | [contract](../harness/build/phase-04a-thin-agent-runtime.md) | [preflight](../harness/context/phase-04a-preflight.md) | [review](../harness/code_review/phase-04a-thin-agent-runtime.md) | build-log |
| 04B Model-backed Runtime | [contract](../harness/build/phase-04b-model-backed-runtime.md) | [preflight](../harness/context/phase-04b-preflight.md) | [review](../harness/code_review/phase-04b-model-backed-runtime.md) | build-log |
| Minimal local Web demo | [contract](../harness/build/phase-minimal-local-web-demo.md) | [preflight](../harness/context/phase-minimal-local-web-demo-preflight.md) | [review](../harness/code_review/phase-minimal-local-web-demo.md) | build-log |
| Local Conversation Intake UX | [contract](../harness/build/phase-local-conversation-intake-ux.md) | [preflight](../harness/context/phase-local-conversation-intake-preflight.md) | [review](../harness/code_review/phase-local-conversation-intake-ux.md) | build-log |
| 04C Persistent Case Store | [contract](../harness/build/phase-04c-persistent-case-store.md) | [preflight](../harness/context/phase-04c-preflight.md) | [review](../harness/code_review/phase-04c-persistent-case-store.md) | [log](../harness/log/phase-04c-persistent-case-store.md) |
| 04D Control-plane operations | [contract](../harness/build/phase-04d-control-plane-operations.md) | [preflight](../harness/context/phase-04d-preflight.md) | [review](../harness/code_review/phase-04d-control-plane-operations.md) | [log](../harness/log/phase-04d-control-plane-operations.md) |
| 05A Temporal CaseWorkflow | [contract](../harness/build/phase-05a-temporal-case-workflow.md) | [preflight](../harness/context/phase-05a-preflight.md) | [review](../harness/code_review/phase-05a-temporal-case-workflow.md) | [log](../harness/log/phase-05a-temporal-case-workflow.md) |
| 06A Durable Web resume | [contract](../harness/build/phase-06a-durable-web-resume.md) | [preflight](../harness/context/phase-06a-preflight.md) | [review](../harness/code_review/phase-06a-durable-web-resume.md) | [log](../harness/log/phase-06a-durable-web-resume.md) |
| 06B1 Local controlled mailbox | [contract](../harness/build/phase-06b1-local-controlled-mailbox.md) | [preflight](../harness/context/phase-06b-controlled-channels-preflight.md) | [review](../harness/code_review/phase-06b1-local-controlled-mailbox.md) | [log](../harness/log/phase-06b1-local-controlled-mailbox.md) |
| 07A Reproducible local portfolio demo | [contract](../harness/build/phase-07a-reproducible-local-portfolio-demo.md) | — | [review](../harness/code_review/phase-07a-reproducible-local-portfolio-demo.md) | [log](../harness/log/phase-07a-reproducible-local-portfolio-demo.md) |
| 03C Fast model distillation (`GO_DISTILLED`, not promoted) | [contract](../harness/build/phase-03c-fast-model-distillation.md) | [preflight](../harness/context/phase-03c-preflight.md) | [Stage 3 decision review](../harness/code_review/phase-03c-stage3-decision.md) | [log](../harness/log/phase-03c-stage2-stage3.md) |

Phase 03B is closed: one frozen QLoRA training run and one canonical Arm B
evaluation are recorded as descriptive evidence, and the accepted decision is
`NO_GO_STOP_PHASE03B`. No additional training, data expansion, rerun,
promotion, or deployment is authorized. The pre-approval proposal that preceded
the executed contract was removed from `docs/planning/` on 2026-09-21; its
content survives in Git history and the executed contract above.

## In progress

- [Phase 07 Portfolio Hardening](../harness/build/phase-07-portfolio-hardening.md) (build-plan PR-16 and PR-17; [log](../harness/log/phase-07-portfolio-hardening.md)). The phase gate is at the end of PR-17.

## Not started

Phase 06B2 (real Provider/email/MCP/credential integration), voice,
authentication, production UI, promoted-model serving, deployment, and
release remain separate unauthorized gates. The full not-done list is in
[limitations.md](limitations.md#not-done).

The telecom specification is the v1 scope. `ProxyLoop` is the platform name, not a claim that telecom, auto negotiation, or other future verticals are already implemented.
