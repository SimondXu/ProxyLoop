# ProxyLoop Build Log

This file is append-only execution evidence. Record only commands actually run and outcomes actually observed. Proposed checks belong in the phase contract, not in this log.

## Phase Status

| Phase | Status | Last evidence |
|---|---|---|
| 00A — repository foundation | Complete | Initial repository layout validated and published before this harness initialization |
| 00B — canonical contracts | Complete | `make preflight`: 17 tests plus format, lint, type, generation, drift, TypeScript, layout, locks, compile, and Compose passed |

## Entries

### 2026-08-22 — Development harness initialization

- Scope: repository goals, plan, domain glossary, model-role configuration, phase contract, and harness documentation only.
- Business implementation: none.
- External side effects: no commit, push, deploy, provider contact, or credential use.
- `make check-layout`: passed; repository foundation, required harness paths, root model, concurrency bound, and required agent fields validated.
- `python3 -m compileall -q scripts`: passed.
- `git diff --check`: passed after the final evidence update.
- `codex features list`: passed and loaded the repository configuration; the sandbox emitted a non-blocking PATH-alias warning.
- `docker compose config --quiet`: passed.
- `pnpm install --lockfile-only --ignore-scripts --offline`: passed with pnpm 10.31.0; no dependency download was required.
- `uv lock --project runtime --check`: passed with CPython 3.12.10 and resolved the existing three-package runtime workspace.
- Correction made during verification: the first root-level `uv lock --check` was invalid because the Python workspace lives under `runtime/`; repository instructions now use the explicit project path.
- Independent review: not required for this documentation/configuration initialization; Phase 00B still requires an independent Terra review before its own completion gate.

### 2026-08-22 — Implementer model routing adjustment

- Decision: keep Sol high as root orchestrator and Terra high as the independent read-only reviewer; change the default implementer from Terra high to Luna xhigh.
- Escalation rule: Luna max is allowed only by explicit per-task override for complex multi-file implementation after architecture and acceptance criteria are frozen.
- Unchanged: Luna medium fast-worker/explorer roles, three-subagent concurrency cap, sandbox boundaries, and the rule requiring explicit delegation.
- `make check-layout`: passed; exact model, reasoning-effort, and sandbox settings for all four custom agents are validated.
- `python3 -m compileall -q scripts`: passed.
- `git diff --check` and repository text trailing-whitespace check: passed.
- `codex features list`: passed and loaded the repository configuration; the sandbox emitted the same non-blocking PATH-alias warning recorded during initialization.
- External side effects: no subagent spawn, commit, push, or deploy.

### 2026-08-22 — Git contribution workflow

- Branch: `chore/development-harness`, created from `main` at `81d28b3` while preserving the complete uncommitted harness change set.
- Policy: short-lived branches, one bounded pull request, repository preflight, Conventional Commits, squash merge, and no direct implementation or commit on `main`.
- Added: `CONTRIBUTING.md`, pull request template, project Git rules in `AGENTS.md`, and a repository-native `make preflight` command.
- `.gitignore`: added only Python package/coverage and TypeScript incremental-build output; `.codex/` and `harness/` remain versioned project content.
- `make preflight`: passed, including layout validation, diff whitespace validation, Python script compilation, and Docker Compose configuration validation.
- `pnpm preflight`: passed through the repository package script.
- `uv lock --project runtime --check`: passed against the existing runtime lock.
- `pnpm install --lockfile-only --ignore-scripts --offline`: passed without downloading dependencies or changing the lockfile.
- CI: `.github/workflows/ci.yml` now runs the same `make preflight` gate for pull requests and pushes to `main`.
- Commit, push, and pull request identifiers are reported in the pull request and task handoff after this log entry is finalized.

### 2026-08-22 — Pull request 1 review remediation

- Review target: `chore/development-harness` at `fe8084e`, pull request 1.
- Blocking finding: the four role files existed, but `.codex/config.toml` did not declare `[agents.<role>]` entries with `config_file` and `description`; official Codex configuration therefore did not register the custom roles.
- Remediation: registered all four roles in `.codex/config.toml`, kept role execution settings in their referenced config layers, and strengthened `scripts/validate_layout.py` to validate the declarations.
- Improvement: changed the CI committed-diff whitespace check from `HEAD^` to the complete pull-request or push commit range so multi-commit changes are covered.
- Durable review: `harness/code_review/pr-1.md`.
- Official configuration reference: confirmed project-local configuration, `review_model`, `[agents.<role>]`, `config_file`, `description`, concurrency, model reasoning effort, and sandbox fields against the current Codex configuration reference.
- `make preflight`: passed after remediation.
- `codex features list`: passed and loaded the remediated repository configuration; the sandbox emitted the previously documented non-blocking PATH-alias warning.

### 2026-08-22 — Phase 00B activation

- Human gate: the user explicitly approved starting Phase 00B after pull request 1 was reviewed and squash merged.
- Base: merged `main` commit `d1d8710f64cd54ff5c7d1472a21eab74fdacb17b`; the post-merge `Repository checks` workflow passed.
- Active branch: `feat/phase-00b-contracts`.
- Status changed from `Prepared, not started` to `In progress` in the phase contract, execution plan, repository instructions, README, and phase table.
- Observed package/test baseline and all six open preflight decisions are recorded in `harness/context/phase-00b-preflight.md`.
- Scope boundary: no domain model, generated artifact, simulator, service, workflow, model, channel, or UI implementation was started during activation.
- Codex Goal: active and restricted to Phase 00B acceptance evidence, independent review, and a hard stop before Phase 01.
- `make preflight`: passed on the activated branch.
- `uv lock --project runtime --check`: passed with CPython 3.12.10 and the existing three-package runtime workspace.

### 2026-08-22 — Phase 00B preflight decisions

- Resolved all six required decisions before domain model implementation; the durable record is `docs/decisions/2026-08-22-contract-wire-format.md`.
- Source seam: hand-authored Pydantic contracts -> committed JSON Schema Draft 2020-12 -> generated TypeScript declarations.
- Generator versions: `json-schema-to-typescript` 15.0.4 and TypeScript 7.0.2, selected from npm registry stable tags and to be pinned by `pnpm-lock.yaml`.
- Wire rules: ProxyLoop UUIDv4 identifiers, opaque external references, timezone-aware UTC RFC 3339 timestamps, `schema_version="1.0"`, positive entity revisions, immutable snapshots, and integer-minor-unit Money.
- Drift rules: generated provenance plus `make contracts` and temporary-output comparison through `make contracts-check`.
- Current local toolchain observed: Python 3.12.10, Node 22.15.1, pnpm 10.31.0, and uv 0.8.4.

### 2026-08-22 — Phase 00B canonical contracts and gate

- Implemented 13 canonical, strict, immutable Pydantic contract documents plus shared value objects under `runtime/packages/contracts/`; no runtime framework, storage, workflow, channel, or model SDK dependency entered the package.
- Added exact UUIDv4, UTC RFC 3339, schema-version, revision, Money, approval/action binding, external Evidence, candidate-only Fast Model completion, and deterministic Completion Decision constraints.
- Added committed JSON Schema Draft 2020-12 and TypeScript declarations generated from the Pydantic source, a compile-time Case fixture, deterministic provenance, `make contracts`, and temporary-output `make contracts-check` drift detection.
- Red/green evidence: the first focused contract run failed because `CANONICAL_MODELS` did not exist; after implementation, `uv run --project runtime --all-packages pytest runtime/packages/contracts/tests/test_contracts.py -q` passed 8 tests.
- Independent review initially requested changes for JSON Schema UUID/UTC parity, approval after expiry, missing schema-level `accept_offer` conditions, and an architecture blacklist. Remediation added portable patterns, approval-window enforcement, `dependentSchemas` conditions, regression probes, and a standard-library-plus-Pydantic import allowlist.
- The review also identified the standard JSON Schema limitation that a parsed mathematical integer cannot preserve whether its source token was `9200` or `9200.0`; the wire-format ADR now records Pydantic as the strict Python ingestion authority and JSON Schema as the portable representable-constraint boundary.
- Final `make preflight`: passed. Observed results were Ruff format 8 files, Ruff lint all checks passed, mypy 5 source files with no issues, pytest 17 passed, generated artifacts matched fresh temporary output, TypeScript compiled the exact Case fixture, repository layout passed, both lock checks passed, scripts compiled, and Docker Compose configuration validated.
- Independent read-only Terra review: blocking findings were remediated and the reviewer recommended approving the gate after durable evidence was added; durable details are in `harness/code_review/phase-00b.md`.
- Final independent rereview: the reviewer reran `make preflight` on the completed evidence state, observed the same 17 passing tests and full gate, confirmed required TypeScript discriminants, and approved Phase 00B with no unresolved blocking findings.
- Scope audit: no Phase 01 simulator behavior or API, database, Temporal, model-call, training, channel, or UI implementation entered the diff.
- Stop condition: Phase 00B is complete locally. Phase 01 remains not started and requires a new explicit user gate.
