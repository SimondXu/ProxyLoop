# ProxyLoop

### A Durable Consumer Negotiation & Task-Completion Agent

ProxyLoop is a portfolio-grade agent platform designed to research, negotiate, follow up, and pursue verifiable completion for consumer tasks. Its first vertical is fictional-provider telecom bill optimization; auto-deal negotiation is a planned future vertical.

The design separates a locally trained Fast Response Model from a hosted Slow Reasoner, and keeps authorization, side effects, and final completion outside the models. It is intentionally simulator-first: no real-carrier contact, credentials, or production-completion claim is included in this repository.

## Current status

Phase 0 repository setup is complete: the monorepo boundaries, documentation, local-tooling configuration, and empty implementation zones are in place. Product services, model training, external channels, and a web UI are not implemented yet.

## Start here

- [Product and ML specification](docs/specs/2026-08-21-telecom-bill-optimization-agent.md)
- [Architecture overview](docs/architecture.md)
- [Monorepo decision](docs/decisions/2026-08-21-monorepo.md)
- [Implementation defaults](docs/decisions/2026-08-22-implementation-defaults.md)
- [Documentation index](docs/README.md)
- [Initial project plan](docs/planning/initial-project-plan.md)
- [Research findings](docs/research/foundations.md)
- [Progress log](docs/planning/progress.md)

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

Run `make check-layout` to validate this Phase 0 structure. It does not claim to run product tests.

## Working product statement

> ProxyLoop represents a consumer within explicitly delegated limits, combines fast local turn policy with deliberate strategy, waits for external events when needed, and recognizes completion only from verified evidence.

The research MVP is mobile-first, text-only, and simulator-based. Home internet remains schema-compatible; email, cross-day workflows, and controlled voice are gated follow-on milestones.
