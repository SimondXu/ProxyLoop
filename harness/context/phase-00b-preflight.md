# Phase 00B Preflight Context

**Status**: In progress

**Checked**: 2026-08-22

**Question**: What must be decided and verified before ProxyLoop writes its canonical domain models?

## Observed Baseline

- `runtime/packages/contracts/pyproject.toml` defines the `proxyloop-contracts` Python 3.12 package with no runtime dependencies yet.
- `runtime/packages/contracts/src/proxyloop_contracts/__init__.py` contains only a phase placeholder; no domain models exist.
- `contracts/jsonschema/` and `contracts/openapi/` exist but contain no generated contract artifacts.
- `tests/contract/` exists but contains no tests.
- `tests/fixtures/` does not exist yet.
- The existing runtime lock resolves the three-package uv workspace.

These statements describe the checkout at branch activation. They are not implementation claims.

## Required Decision Record

Resolve each item before writing domain models. Record primary sources, selected versions, rejected alternatives, and the verification command.

| Decision | Status | Output |
|---|---|---|
| TypeScript generator and reproducible version | Open | Phase context or ADR |
| Identifier representation at JSON boundaries | Open | Phase context or ADR |
| Timestamp and timezone serialization | Open | Phase context or ADR |
| Contract schema version versus entity revision | Open | Phase context or ADR |
| Decimal, money, and currency representation | Open | Phase context or ADR |
| Generated-artifact provenance and drift command | Open | Phase context or ADR |

## First Execution Slice

1. Inspect current Python, Node, uv, and pnpm locks and available repository commands.
2. Compare one or two reproducible Python-to-TypeScript generation paths using current primary documentation.
3. Freeze the six decisions together so identifiers, timestamps, money, revisions, generated schemas, and TypeScript types do not drift independently.
4. Add the smallest failing contract tests only after those decisions are recorded.

## Boundaries

- Do not implement simulator transitions, services, persistence, Temporal workflows, model calls, channels, or UI.
- Do not hand-author a second TypeScript domain model.
- Do not claim Phase 00B complete until every acceptance criterion has evidence and independent review is resolved.
