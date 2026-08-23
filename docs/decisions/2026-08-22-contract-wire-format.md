# Freeze the Phase 00B Contract Wire Format and Generation Path

## Status

Accepted for contract schema version `1.0`.

## Context

ProxyLoop needs one canonical contract interface shared by Python runtime code, JSON Schema validation, and TypeScript consumers. The seam must preserve authorization and completion semantics without creating a second hand-maintained domain model.

The chosen representation must also distinguish a wire-format change from an optimistic update to one business entity, preserve money exactly across Python and JavaScript, and generate deterministically from committed dependencies.

## Decision

### Source and generation path

- Pydantic models under `runtime/packages/contracts/` are the only hand-authored contract source.
- Pydantic emits one bundled JSON Schema Draft 2020-12 document under `contracts/jsonschema/`.
- `json-schema-to-typescript` `15.0.4` generates TypeScript declarations from that committed schema. TypeScript is pinned to `7.0.2` for the compile-time fixture check.
- `pnpm-lock.yaml` and `runtime/uv.lock` pin the complete tool and Python dependency graphs.
- Generated files carry a source path, schema version, generator identity, and regeneration command.
- `make contracts` regenerates artifacts. `make contracts-check` generates into a temporary directory and fails when committed artifacts differ.

### Identifiers

- ProxyLoop-owned entity identifiers are UUID version 4 values and serialize as canonical lowercase, hyphenated strings.
- Provider, message, model, prompt, dataset, and other externally assigned references remain non-empty opaque strings; the contract does not reinterpret them as ProxyLoop UUIDs.

### Timestamps

- Contract timestamps are RFC 3339 date-times with an explicit timezone.
- Canonical output is UTC with the `Z` suffix.
- Naive timestamps and non-UTC input offsets are rejected instead of silently normalized.

### Schema versions and entity revisions

- `schema_version` identifies the wire contract and is the literal string `1.0` for this phase.
- `revision` is a positive optimistic-concurrency counter for one mutable business entity.
- A new entity state creates a new immutable contract snapshot with an incremented revision; contracts are frozen after validation.
- References that authorize behavior carry both the target identifier and target revision.

### Money and currency

- Money uses signed integer minor units plus a three-letter uppercase currency code.
- Prices, totals, and budgets apply local non-negative constraints; signed amounts remain available for credits and adjustments.
- Non-integral numbers and decimal strings are not accepted at either validation seam. The strict Pydantic ingestion boundary also rejects a lexically floating JSON value such as `9200.0`; standard JSON Schema treats that value as the mathematical integer `9200` after parsing and cannot distinguish the original token spelling.
- Aggregates reject mixed currencies.

## Consequences

- Python validation, JSON Schema, and TypeScript declarations share one source and one drift gate.
- TypeScript cannot express every JSON Schema runtime constraint, so TypeScript provides compile-time shape compatibility only. Pydantic is authoritative at the Python ingestion boundary; JSON Schema is the portable shape and representable-constraint boundary. Cross-document referential checks remain the responsibility of deterministic domain policy in later phases.
- Adding a field without changing meaning may retain schema version `1.0` only when the compatibility policy permits it; breaking wire changes require a new schema version and migration decision.
- UUIDv4 is not time ordered. Persistence indexes may add separate timestamps later rather than changing public identifiers during Phase 00B.
- Currency exponent rules are not modeled in Phase 00B; minor-unit interpretation is owned by the currency code and downstream presentation logic.

## Rejected Alternatives

- Hand-written TypeScript models: rejected because they create a second mutable source of truth.
- Direct Python-to-TypeScript generators that bypass committed JSON Schema: rejected because the JSON Schema artifact is itself a required public validation seam.
- Floating-point money: rejected because binary floating-point cannot preserve exact consumer prices and fees.
- Decimal strings at the wire seam: rejected because they add parsing and canonicalization rules without improving the first-version use cases.
- Database sequence identifiers or prefixed ad hoc strings: rejected because they couple the contract to storage or project-specific parsing rules.

## Primary References

- Pydantic JSON Schema: https://pydantic.dev/docs/validation/latest/concepts/json_schema/
- JSON Schema Draft 2020-12: https://json-schema.org/draft/2020-12
- json-schema-to-typescript: https://github.com/bcherny/json-schema-to-typescript
- RFC 3339 timestamps: https://www.rfc-editor.org/rfc/rfc3339
- RFC 9562 UUIDs: https://www.rfc-editor.org/rfc/rfc9562
