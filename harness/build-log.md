# ProxyLoop Build Log

This file is append-only execution evidence. Record only commands actually run and outcomes actually observed. Proposed checks belong in the phase contract, not in this log.

## Phase Status

| Phase | Status | Last evidence |
|---|---|---|
| 00A — repository foundation | Complete | Initial repository layout validated and published before this harness initialization |
| 00B — canonical contracts | Complete | `make preflight`: 17 tests plus format, lint, type, generation, drift, TypeScript, layout, locks, compile, and Compose passed |
| 01A — deterministic Provider loop | Complete | Independent `make preflight`: 26 tests plus the complete repository gate passed; matching-forgery and no-mutation probes were rejected |

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

### 2026-08-23 — Pull request 2 review and merge

- Live GitHub state before merge: PR #2 was open, non-draft, `MERGEABLE`, and `CLEAN`; `phase-gate` and GitGuardian both passed.
- Root review: complete source, tests, generators, dependency/CI changes, phase evidence, and durable independent review were inspected with no new blocking finding.
- Fresh local `make preflight` on PR head passed the Phase 00B gate with 17 tests.
- Squash merge: PR #2 merged to `main` as `98a751418271d0a16e6ec5c838cc2ffbff4745bf` at 2026-08-23T03:30:57Z.
- Local `main` was fast-forwarded to the same commit before `feat/phase-01-provider-simulator` was created.

### 2026-08-23 — Phase 01A deterministic Provider loop

- Human gate: the user explicitly authorized Phase 01A implementation after PR #2 merge.
- Scope: one fictional mobile Provider, one deterministic success episode, one offer state path, exact approval, Provider confirmation Evidence, deterministic completion verification, and JSON CLI only.
- Red evidence: `uv run --project runtime --all-packages pytest tests/integration/test_phase_01a_simulator.py -q` failed during collection with `ModuleNotFoundError: proxyloop_provider_simulator` before implementation.
- First green correction: strict canonical Python constructors rejected string UUID inputs; the implementation now constructs `UUID` values explicitly and serializes strings only at the JSON seam.
- Final focused command: `uv run --project runtime --all-packages pytest tests/integration/test_phase_01a_simulator.py tests/contract/test_phase_01a_architecture.py -q` passed 8 tests.
- `make simulator`: passed and emitted deterministic JSON for Provider `pine-mobile`, state history `available -> offered -> awaiting_approval -> confirmed`, exact approved Action Intent references, confirmation Evidence, and verifier-owned `decision=complete`.
- Final `make preflight`: passed. Observed results were Ruff format 17 files, Ruff lint all checks passed, mypy 12 source files with no issues, pytest 25 passed, generated contract artifacts matched, TypeScript compiled, repository layout passed, uv resolved 26 packages from the committed lock, pnpm frozen/offline lock check passed, Python scripts compiled, and Docker Compose configuration validated.
- Adversarial coverage: approval use at expiry leaves the Provider awaiting approval with no confirmation/Evidence; repeated offer issue is rejected without state mutation; forged Evidence and an evidenced forbidden change cannot produce completion.
- Dependency audit: `telecom_domain` imports only standard library plus canonical contracts; `provider_simulator` additionally depends inward on `telecom_domain`; no service, persistence, workflow, channel, model, or ML dependency entered either package.
- Root integration review: initial UUID, constraint/current-state, and evaluation-timing findings were remediated; durable details are in `harness/code_review/phase-01a-root.md`.
- Independent review: not run. The root implementing orchestrator cannot independently approve its own change, so Phase 01A remains `Implementation complete; independent review pending`.
- Explicitly unrun/out of scope: browser, API, authentication, PostgreSQL, Temporal, PydanticAI/model, training, benchmark, cloud, GPU, voice, phone, email, real-provider, deployment, and production E2E checks.
- Stop condition: do not begin Phase 01B or any later roadmap phase until this implementation receives independent review and a new human gate.

### 2026-08-23 — Phase 01A independent review and remediation

- Initial independent decision: Request Changes. The reviewer demonstrated that a caller could forge a new confirmation identifier, recompute its hash, update the Evidence reference/hash consistently, and receive `complete` because verification did not consult the Provider's held state.
- Documentation finding: README listed `make simulator` but incorrectly said the listed commands did not run a Provider simulator.
- Remediation ownership: after explicit user authorization for subagents, a bounded implementer added a single confirmation-authority lookup seam, wired the real fictional Provider into verification, added the internally consistent forgery regression, and corrected README. No other phase or subsystem was added.
- Remediation red evidence: the new regression initially failed with `TypeError: CompletionVerification.__init__() got an unexpected keyword argument 'confirmation_authority'` before the authority seam existed.
- Implementer focused evidence: 9 Phase 01A tests passed; affected Ruff format/lint and mypy checks passed; `git diff --check` passed.
- Independent rereview: Approve with no unresolved blocking findings. The reviewer reran the focused suite with 9 passing tests, `make preflight` with 26 passing tests and the complete repository gate, `make simulator`, and diff checks.
- Adversarial rereview: the matching-forgery regression passed. A separate no-Provider-mutation probe returned `needs_replan` with `provider_confirmation_mismatch` and no Evidence identifier.
- Durable review: `harness/code_review/phase-01a.md`.
- Residual boundary: the in-memory simulator trusts the injected confirmation authority. Durable authenticated or signed external-Provider receipts remain future work, not a Phase 01A requirement.
- Final root verification after durable evidence and status updates: `make preflight` passed with Ruff format on 17 files, Ruff lint, mypy on 12 source files, 26 tests, contract generation/drift, TypeScript, layout, uv/pnpm lock, Python compile, and Compose checks all passing.
- Final root `make simulator`: passed and emitted the deterministic `pine-mobile` episode ending in Provider state `confirmed` and verifier decision `complete`.
- Stop condition: Phase 01A is complete locally. Phase 01B and all later roadmap phases remain not started and require a new explicit human gate.
