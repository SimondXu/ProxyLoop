# ProxyLoop

### A Durable Consumer Negotiation & Task-Completion Agent

ProxyLoop is a portfolio-grade agent platform designed to research, negotiate, follow up, and pursue verifiable completion for consumer tasks. Its first vertical is fictional-provider telecom bill optimization; auto-deal negotiation is a planned future vertical.

The design separates a project-owned Fast Response Model candidate from a hosted Slow Reasoner, and keeps authorization, side effects, and final completion outside the models. One bounded QLoRA training smoke and one canonical Arm B evaluation have completed as descriptive evidence; the final decision is No-Go and no production-completion claim is included. The repository is intentionally simulator-first: no real-carrier contact or credentials are included.

## Current status

Phase 07A is complete locally and independently approved, and the Harness has
returned to idle. The Local Conversation Intake UX, durable Web Case flow,
PostgreSQL/Temporal Runtime, and synthetic `local_mailbox` are integrated;
Phase 03B remains a final `NO_GO_STOP_PHASE03B`. No additional
training, data expansion, rerun, model promotion, real channel, deployment, or
release is authorized. See [`harness/status.toml`](harness/status.toml) for
current authorization boundaries and [`PLANS.md`](PLANS.md) for phase history.

## Start here

- [Product and ML specification](docs/specs/2026-08-21-telecom-bill-optimization-agent.md)
- [Architecture overview](docs/architecture.md)
- [Monorepo decision](docs/decisions/2026-08-21-monorepo.md)
- [Implementation defaults](docs/decisions/2026-08-22-implementation-defaults.md)
- [Documentation index](docs/README.md)
- [Phase 07A portfolio evidence](docs/portfolio-demo.md)
- [Initial project plan](docs/planning/initial-project-plan.md)
- [Research findings](docs/research/foundations.md)
- [Progress log](docs/planning/progress.md)
- [Contribution and Git workflow](CONTRIBUTING.md)
- [Development goals](GOALS.md)
- [Execution plan](PLANS.md)
- [Domain language](CONTEXT.md)
- [Current Harness state](harness/status.toml)
- [Development Harness](harness/README.md)
- [Completed Phase 00B contract](harness/build/phase-00b-contracts.md)
- [Completed Phase 01A simulator contract](harness/build/phase-01a-provider-simulator.md)
- [Completed Phase 01B simulator benchmark contract](harness/build/phase-01b-simulator-benchmark.md)
- [Phase 02 data-factory contract and local gate](harness/build/phase-02-data-factory.md)
- [Phase 03A0 Fast/Slow architecture gate](harness/build/phase-03a0-fast-slow-architecture.md)
- [Phase 03A1 deterministic Harness](harness/build/phase-03a1-harness.md)
- [Phase 03A1 untuned Baselines](harness/build/phase-03a1-baselines.md)
- [Phase 03A1 hosted baseline reliability rerun](harness/build/phase-03a1-hosted-rerun.md)
- [Phase 03A1 evaluation-validity smoke](harness/build/phase-03a1-evaluation-validity-smoke.md)
- [Completed Phase 04A Thin Agent Runtime](harness/build/phase-04a-thin-agent-runtime.md)
- [Phase 04A independent review](harness/code_review/phase-04a-thin-agent-runtime.md)
- [Completed Phase 04B Model-backed Thin Agent Runtime](harness/build/phase-04b-model-backed-runtime.md)
- [Minimal local Web demo contract](harness/build/phase-minimal-local-web-demo.md)
- [Local Conversation Intake UX contract](harness/build/phase-local-conversation-intake-ux.md)
- [Phase 03B Qwen3-4B controlled-smoke closeout](harness/build/phase-03b-qwen-qlora-smoke.md)
- [Phase 03B final comparison](data/experiments/phase-03b-qlora-smoke/results/comparison.md)
- [Original Phase 03B proposal](docs/planning/phase-03b-qwen-qlora-experiment.md)

Run the local scripted Runtime server with:

```text
make runtime-server
```

It binds `127.0.0.1:8000`. Model mode is explicit and requires
`PROXYLOOP_MODEL_API_KEY`, `PROXYLOOP_MODEL_BASE_URL`, and
`PROXYLOOP_MODEL_NAME` in the process environment:

```text
uv run --project runtime --all-packages python -m proxyloop_api.server --mode model
```

The server does not load `.env` files. No real model smoke is part of the
automated gate.

## Reproducible local portfolio demo

Prerequisites are Docker with Compose, `uv`, `pnpm`, and the repository's
already-installed dependencies. The demo uses only loopback ports, the
repository's local PostgreSQL fixture credentials, the deterministic scripted
Runtime, the synthetic mailbox, and the fictional Provider simulator. It does
not download or call a model and does not contact Gmail, Voice, or an external
Provider.

Start the complete local stack from a clean checkout:

```text
make portfolio-demo
```

The command starts the existing Compose PostgreSQL and Temporal server,
then the host workflow worker, FastAPI Runtime, and existing Next.js Web app.
Startup prints the Web URL, Runtime readiness URL, Temporal address, log
directory, stop command, and the fixed scene order:

1. Scene A — use the Web conversation to confirm the four telecom facts,
   approve the exact offer, and observe one fictional Provider execution and
   authoritative completion Evidence.
2. Stop and reset the local demo state, then restart `make portfolio-demo` to
   bring up a fresh stack for the independent channel scene.
3. Scene B — from a second terminal, run `make portfolio-demo-channel` to create a fresh scripted Case,
   post the signed raw-byte `local_mailbox` fixture, replay it exactly, observe
   one accepted synthetic delivery, post the delivered callback, and verify
   browser-projection isolation from PostgreSQL authority.

Normal stop is bounded and preserves PostgreSQL data:

```text
make portfolio-demo-stop
```

To remove only the named demo volume and start Scene B from a fresh state, use
the explicit reset command. It prints its exact scope before removing
the Phase 07A-only `proxyloop-portfolio-demo_postgres-data` volume:

```text
make portfolio-demo-reset
```

Reset stops the stack. Run `make portfolio-demo` again in the first terminal,
wait for the printed readiness information, and then run `make portfolio-demo-channel`
from a second terminal.

The focused real-local recovery check reuses the accepted Phase 06B1
lost-response/idempotent retry path against PostgreSQL and Temporal:

```text
make portfolio-demo-recovery
```

Expected Scene B results are one server-correlated inbox identity, one outbox
delivery identity, exact duplicate deduplication, one accepted synthetic
Provider reference, one delivered callback/receipt, two authoritative channel
Evidence records, and no channel content/provider reference/artifact hash in
the browser Case projection. Synthetic acceptance and delivery are local
observations only; they do not prove real-provider delivery, production
exactly-once effects, or production readiness.

Troubleshooting: if startup reports an unavailable port or dependency, inspect
the printed log directory and
`docker compose --project-name proxyloop-portfolio-demo ps`, then run
`make portfolio-demo-stop` before retrying. If Scene B reports that state is
not fresh, stop/reset, restart `make portfolio-demo`, and rerun Scene B. The recovery command
also needs the primary Temporal service from `make portfolio-demo`; it creates
and stops only the temporary `postgres-test` service for its focused check.

Implemented and locally verified are the deterministic scripted Case,
PostgreSQL authority, Temporal ordering/retry/recovery, fictional Provider, and
synthetic mailbox boundary. Browser/manual checks completed at 1280x900 and
375x812 with no horizontal overflow or warning/error console output; stopping
and restarting the stack while preserving the isolated volume recovered the
same verified Case, single execution, and Evidence receipt. Gmail is a future proposed
seam at the API verification/channel-adapter boundary. Voice is a future
proposed seam at the deferred LiveKit/SIP channel worker. Both require separate
policy, credential, security, retention, and evaluation gates.

## Repository layout

```text
apps/        Next.js conversation-first local Web experience
runtime/     Python contracts and durable-agent services
ml/          Independent data, training, evaluation, and serving environment
voice/       Deferred LiveKit/SIP worker environment
contracts/   Generated API and JSON Schema artifacts
data/        Versioned manifests, schemas, and redacted samples only
infra/       Local infrastructure configuration and migrations
tests/       Contract, integration, and end-to-end test lanes
```

Run `make preflight-fast` for a quick Harness and diff check while iterating, use the relevant focused target for changed behavior, and run `make preflight` once for the complete final repository gate:

```text
make format          Format Python contract and verification code
make preflight-fast  Validate Harness layout, Python syntax, and Git whitespace
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

Repository-level agent behavior is defined in [AGENTS.md](AGENTS.md), and the branch/commit/PR workflow is defined in [CONTRIBUTING.md](CONTRIBUTING.md). Work is organized as one explicitly approved phase at a time: prepare a phase contract, execute its red/green/verification loop, obtain an independent review for material changes, record current evidence under [harness/log/](harness/log/), and stop at the gate.

The default Codex role split is Sol high for root orchestration, Luna xhigh for clearly specified implementation, Terra high for independent review, and Luna medium for narrow mechanical work or bounded exploration. Luna max is an explicit escalation for complex implementation, not a standing default. Sol assigns subagents when useful, reconciles their work, and owns final PR approval and merge; model choice never relaxes file ownership, safety, evidence, or phase-scope requirements.

## Working product statement

> ProxyLoop represents a consumer within explicitly delegated limits, combines fast local turn policy with deliberate strategy, waits for external events when needed, and recognizes completion only from verified evidence.

The research MVP is mobile-first, text-only, and simulator-based. Home internet remains schema-compatible; email, cross-day workflows, and controlled voice are gated follow-on milestones.
