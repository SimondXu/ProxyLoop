# Phase 00B Independent Contract Review

**Target**: `feat/phase-00b-contracts` working tree against merged `main` at `d1d8710`

**Reviewer**: independent read-only Terra role

**Initial decision**: Request changes

**Decision after remediation and evidence**: Approved; no unresolved blocking findings

## Findings and resolutions

### 1. JSON Schema did not enforce the frozen UUIDv4 and UTC rules

**Severity**: P1

The first generated schema used `format: uuid4`, which the standard Python JSON Schema format checker did not recognize, and ordinary `date-time` accepted non-UTC offsets. Direct probes showed values that Pydantic rejected could pass the portable schema boundary.

**Resolution**: The canonical annotated types now emit a standard `uuid` format plus a canonical lowercase UUIDv4 pattern, and a date-time format plus an RFC 3339 UTC pattern. Cross-schema tests reject UUIDv1, non-UTC offsets, and naive timestamps.

### 2. Approval could be decided after expiry

**Severity**: P1

An `approved` or `rejected` request originally required `decided_at` but did not require the decision to occur before `expires_at`.

**Resolution**: Approved and rejected decisions now require `requested_at <= decided_at < expires_at`. A regression test exercises an approval one minute after expiry.

### 3. Consequential-action conditions existed only in Pydantic

**Severity**: P1

The first JSON Schema could accept `accept_offer` without an exact offer reference even though the Pydantic after-validator rejected it.

**Resolution**: Canonical schema metadata now emits Draft 2020-12 `dependentSchemas` rules. `ActionIntent` requires an offer reference, material terms, and approval; `ApprovalRequest` requires its offer reference. Invalid fixtures are checked at both the Pydantic and JSON Schema seams. The conditional metadata does not degrade generated TypeScript: `CompletionDecision` remains an explicit interface.

### 4. Architecture dependency enforcement used a blacklist

**Severity**: P2

A framework blacklist could miss unlisted database, channel, network, or model SDKs.

**Resolution**: The architecture test now permits only Python standard-library modules and Pydantic, while package metadata independently requires a Pydantic-only runtime dependency surface.

## Intentional boundary

Standard JSON Schema defines `integer` mathematically after JSON parsing, so it cannot distinguish source tokens `9200` and `9200.0`. Pydantic strict JSON validation rejects the latter; the portable schema still rejects non-integral values and decimal strings. The wire-format ADR now states this boundary explicitly instead of claiming impossible lexical parity.

## Verification and gate

The reviewer independently reran repository gates and direct semantic probes after remediation. The final repository evidence is recorded in `harness/build-log.md`. No Phase 01 simulator, service, persistence, workflow, model, channel, or UI implementation was found.

Phase 00B has no unresolved blocking findings and may stop at its completion gate.
