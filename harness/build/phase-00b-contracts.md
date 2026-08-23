# Phase 00B — Canonical Contracts and Contract Verification

**Status**: Complete — local gate passed 2026-08-22; Phase 01 not started

**Activation**: Explicitly approved by the user on 2026-08-22. Active branch: `feat/phase-00b-contracts`, based on merged `main` commit `d1d8710`.

**Roadmap source**: Phase 0 in `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`

## Objective

Establish one framework-independent, versioned domain contract package and prove that a representative case payload round-trips through Python, generated JSON Schema, and generated TypeScript without contract drift.

## Inputs

- `GOALS.md`
- `CONTEXT.md`
- `docs/architecture.md`
- `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`
- `docs/decisions/2026-08-22-implementation-defaults.md`
- `docs/decisions/2026-08-22-contract-wire-format.md`
- `harness/context/phase-00b-preflight.md`
- existing skeleton under `runtime/packages/contracts/`, `contracts/`, and `tests/contract/`

## In Scope

- canonical Pydantic models for:
  - Case
  - Consumer Goal
  - Constraint
  - Bill Snapshot
  - Fact Ledger
  - Strategy Packet
  - Fast Turn Decision
  - Provider Offer
  - Action Intent
  - Approval Request
  - Evidence
  - Completion Decision
  - Model Trace
- explicit identifiers, schema versions, timestamps, immutable snapshot/version semantics, and provenance fields;
- strict validation for unknown fields and invalid state combinations where the contract can decide them locally;
- generated JSON Schema under `contracts/jsonschema/`;
- one selected, documented TypeScript generation path and generated artifacts under `contracts/typescript/`;
- representative valid and invalid fixtures under `tests/fixtures/`;
- Python-to-schema-to-TypeScript round-trip or compatibility test;
- contract-generation drift check;
- architecture checks that prevent framework, database, channel, or model SDK dependencies in the canonical contract package;
- repository-native format, lint, type-check, unit-test, generation, and drift commands;
- reproducible dependency and lock updates required by this phase.

## Non-Goals

- provider simulator transitions or scenarios;
- FastAPI routes, database tables, or repositories;
- Temporal workflows or activities;
- model provider calls, prompts, training, serving, or evaluation;
- email, voice, browser automation, or real-provider integration;
- production web UI or speculative frontend API clients;
- GRPO, vector databases, RAG, or additional verticals.

## Required Preflight Decisions

Resolve these before writing domain models and record the result in phase context or a durable ADR when warranted:

1. TypeScript generator and its reproducible version.
2. Identifier representation at JSON boundaries.
3. Timestamp and timezone serialization rule.
4. Contract-level version fields versus entity revision fields.
5. Decimal/money representation and currency constraints.
6. How generated artifacts declare their source and drift command.

Prefer the simplest path that produces stable discriminated unions and does not introduce a runtime framework dependency into the contract package.

## Expected Ownership

```text
runtime/packages/contracts/   canonical Python contracts and package-local tests
contracts/jsonschema/         generated JSON Schema
contracts/typescript/         generated TypeScript artifacts
tests/contract/               cross-language and architecture checks
tests/fixtures/               representative versioned payloads
scripts/                      generation or drift entry points when justified
```

Do not create parallel hand-written Python and TypeScript domain models.

## Build Loop

### 1. Preflight

- inspect current locks, package metadata, and baseline checks;
- map every contract term to `CONTEXT.md` and the product specification;
- record assumptions and the selected generation path;
- confirm dirty files before editing.

### 2. Red

Add the smallest failing checks for:

- a representative valid Case fixture;
- at least one unknown-field rejection;
- a stale or mismatched approval reference;
- an unsupported completion claim without sufficient evidence;
- forbidden contract-package imports;
- generated-artifact drift.

### 3. Green

Implement only the contract surface and tooling needed for the failing checks. Keep runtime frameworks, storage behavior, simulator transitions, and model policy outside the package.

### 4. Refactor

Refactor only demonstrated duplication or confusing boundaries. Do not create generic base classes, adapter seams, or extension registries for hypothetical future consumers.

### 5. Verify

The phase must establish exact repository commands for:

- Python format and lint;
- Python type checking;
- unit and contract tests;
- schema and TypeScript generation;
- generated-artifact drift;
- architecture dependency rules;
- root layout and lock checks.

Run focused checks first, then the complete phase check suite. Record exact commands and results in `harness/build-log.md`.

### 6. Review

An independent Terra reviewer must compare the diff and evidence against this file. Store a durable review artifact under `harness/code_review/` when findings or gate rationale are material. The implementer may remediate findings but cannot self-approve the phase.

## Acceptance Criteria

- [x] The canonical package installs reproducibly from the committed lock state.
- [x] Contract names and meanings match `CONTEXT.md`; no duplicate synonym models exist.
- [x] Models reject unknown fields and invalid local invariants with deterministic errors.
- [x] Approvals bind to the intended Case revision, action, material terms, and expiry.
- [x] A model output alone cannot constitute Evidence or a Completion Decision.
- [x] One representative payload validates in Python and against generated JSON Schema, and is accepted by the generated TypeScript boundary.
- [x] Representative invalid fixtures fail for the intended reason.
- [x] Generated JSON Schema and TypeScript artifacts have a reproducible generation and drift command.
- [x] Architecture tests allow only the Python standard library and Pydantic in the canonical package.
- [x] Repository-native format, lint, type, test, and contract checks pass.
- [x] No simulator, API, database, workflow, channel, model-call, training, or UI implementation entered the diff.
- [x] Verification evidence is recorded in `harness/build-log.md`.
- [x] Independent review has no unresolved blocking findings.

## Stop Condition

When every acceptance criterion has evidence, mark Phase 00B complete, report the gate, and stop. Do not start Phase 01 or create simulator behavior without explicit user approval.
