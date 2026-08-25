# ProxyLoop

### A Durable Consumer Negotiation & Task-Completion Agent

ProxyLoop is a portfolio-grade agent platform designed to research, negotiate, follow up, and pursue verifiable completion for consumer tasks. Its first vertical is fictional-provider telecom bill optimization; auto-deal negotiation is a planned future vertical.

The design separates a locally trained Fast Response Model from a hosted Slow Reasoner, and keeps authorization, side effects, and final completion outside the models. It is intentionally simulator-first: no real-carrier contact, credentials, or production-completion claim is included in this repository.

## Current status

Phase 00A through Phase 03A1-V are complete. The deterministic Harness was squash merged as `e08c9b6` through PR #8, the untuned Qwen/Terra baseline matrix completed PR #9, and the evaluation erratum completed PR #10. The corrected r4 hosted matrix then completed through 29qg with auditable usage. A six-episode r5 validity smoke using the same Qwen/Terra path improved the selected baseline from 0/6 to 5/6 after model-view and prompt-contract parity; its remaining failure isolated a hidden twelve-month-cost evaluator predicate. This is diagnostic evidence, not a training-quality claim. Phase 02's human review sample remains `pending_human` and `training_ready=false`. No implementation phase is active; training, product services, external channels, and a web UI are not implemented.

## Start here

- [Product and ML specification](docs/specs/2026-08-21-telecom-bill-optimization-agent.md)
- [Architecture overview](docs/architecture.md)
- [Monorepo decision](docs/decisions/2026-08-21-monorepo.md)
- [Implementation defaults](docs/decisions/2026-08-22-implementation-defaults.md)
- [Documentation index](docs/README.md)
- [Initial project plan](docs/planning/initial-project-plan.md)
- [Research findings](docs/research/foundations.md)
- [Progress log](docs/planning/progress.md)
- [Contribution and Git workflow](CONTRIBUTING.md)
- [Development goals](GOALS.md)
- [Execution plan](PLANS.md)
- [Domain language](CONTEXT.md)
- [Development harness](harness/README.md)
- [Completed Phase 00B contract](harness/build/phase-00b-contracts.md)
- [Completed Phase 01A simulator contract](harness/build/phase-01a-provider-simulator.md)
- [Completed Phase 01B simulator benchmark contract](harness/build/phase-01b-simulator-benchmark.md)
- [Phase 02 data-factory contract and local gate](harness/build/phase-02-data-factory.md)
- [Phase 03A0 Fast/Slow architecture gate](harness/build/phase-03a0-fast-slow-architecture.md)
- [Phase 03A1 deterministic Harness](harness/build/phase-03a1-harness.md)
- [Phase 03A1 untuned Baselines](harness/build/phase-03a1-baselines.md)
- [Phase 03A1 hosted baseline reliability rerun](harness/build/phase-03a1-hosted-rerun.md)
- [Phase 03A1 evaluation-validity smoke](harness/build/phase-03a1-evaluation-validity-smoke.md)

## Repository layout

```text
apps/        Next.js user experience (deferred)
runtime/     Python contracts and durable-agent services
ml/          Independent data, training, evaluation, and serving environment
voice/       Deferred LiveKit/SIP worker environment
contracts/   Generated API and JSON Schema artifacts
data/        Versioned manifests, schemas, and redacted samples only
infra/       Local infrastructure configuration and migrations
tests/       Contract, integration, and end-to-end test lanes
```

Run `make preflight` for the complete repository gate, or use the focused Phase 00B commands:

```text
make format          Format Python contract and verification code
make validate        Run format, lint, type, test, drift, and layout checks
make contracts       Regenerate committed JSON Schema and TypeScript contracts
make contracts-check Verify generated artifacts and compile the TypeScript fixture
make simulator       Emit the deterministic Phase 01A success episode as JSON
make benchmark       Emit the deterministic Phase 01B environment-ceiling report
make benchmark-check Verify the committed split/report artifacts and Phase 01B gate
make data-pilot      Emit the deterministic Phase 02 pilot cost/quality report
make data-pilot-check Verify Phase 02 schema, manifest, quarantine, report, and sample drift
make hosted-rerun-check Verify the source-bound Phase 03A1 r4 hosted report
make validity-smoke-check Verify the source-bound Phase 03A1 r5 diagnostic report
```

These commands validate the canonical contract boundary, deterministic simulator gates, and the Phase 02 Data Factory pilot. `make simulator` runs the Phase 01A success episode; `make benchmark` runs Phase 01B's scripted environment ceiling; `make data-pilot` regenerates the deterministic one-turn pilot report with zero external model calls. None runs a learned model, model training, product service, workflow engine, external channel, or browser test.

## Development workflow

Repository-level agent behavior is defined in [AGENTS.md](AGENTS.md), and the branch/commit/PR workflow is defined in [CONTRIBUTING.md](CONTRIBUTING.md). Work is organized as one explicitly approved phase at a time: prepare a phase contract, execute its red/green/verification loop, obtain an independent review for material changes, record evidence in [harness/build-log.md](harness/build-log.md), and stop at the gate.

The default Codex role split is Sol high for root orchestration, Luna xhigh for clearly specified implementation, Terra high for independent review, and Luna medium for narrow mechanical work or bounded exploration. Luna max is an explicit escalation for complex implementation, not a standing default. Sol assigns subagents when useful, reconciles their work, and owns final PR approval and merge; model choice never relaxes file ownership, safety, evidence, or phase-scope requirements.

## Working product statement

> ProxyLoop represents a consumer within explicitly delegated limits, combines fast local turn policy with deliberate strategy, waits for external events when needed, and recognizes completion only from verified evidence.

The research MVP is mobile-first, text-only, and simulator-based. Home internet remains schema-compatible; email, cross-day workflows, and controlled voice are gated follow-on milestones.
