# Phase 00B Preflight Context

**Status**: Complete; decisions implemented and verified

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

The six decisions were frozen before domain model implementation in `docs/decisions/2026-08-22-contract-wire-format.md`.

| Decision | Status | Output |
|---|---|---|
| TypeScript generator and reproducible version | Accepted | `json-schema-to-typescript==15.0.4`; TypeScript `7.0.2`; exact pnpm lock |
| Identifier representation at JSON boundaries | Accepted | ProxyLoop UUIDv4 strings; external references remain opaque strings |
| Timestamp and timezone serialization | Accepted | RFC 3339, timezone required, UTC `Z` output only |
| Contract schema version versus entity revision | Accepted | `schema_version="1.0"`; positive `revision`; immutable snapshots |
| Decimal, money, and currency representation | Accepted | signed integer minor units plus uppercase three-letter currency |
| Generated-artifact provenance and drift command | Accepted | generated headers/metadata; `make contracts`; `make contracts-check` |

## Sources Checked

- Pydantic JSON Schema and strict-model documentation, checked 2026-08-22.
- json-schema-to-typescript CLI and options, checked 2026-08-22.
- npm registry stable versions for json-schema-to-typescript and TypeScript, checked 2026-08-22.
- JSON Schema Draft 2020-12, RFC 3339, and RFC 9562, checked 2026-08-22.

## First Execution Slice

1. Add the smallest failing tests for strict inputs, UTC timestamps, money, revisions, approval binding, evidence authority, and completion authority.
2. Implement the canonical Pydantic models behind one strict contract interface.
3. Generate and drift-check JSON Schema plus TypeScript from that source.
4. Prove the representative Case fixture at all three seams.

## Boundaries

- Do not implement simulator transitions, services, persistence, Temporal workflows, model calls, channels, or UI.
- Do not hand-author a second TypeScript domain model.
- Do not claim Phase 00B complete until every acceptance criterion has evidence and independent review is resolved.
