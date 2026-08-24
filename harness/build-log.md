# ProxyLoop Build Log

This file is append-only execution evidence. Record only commands actually run and outcomes actually observed. Proposed checks belong in the phase contract, not in this log.

## Phase Status

| Phase | Status | Last evidence |
|---|---|---|
| 00A — repository foundation | Complete | Initial repository layout validated and published before this harness initialization |
| 00B — canonical contracts | Complete | `make preflight`: 17 tests plus format, lint, type, generation, drift, TypeScript, layout, locks, compile, and Compose passed |
| 01A — deterministic Provider loop | Complete | Independent `make preflight`: 26 tests plus the complete repository gate passed; matching-forgery and no-mutation probes were rejected |
| 01B — simulator breadth and benchmark | Complete | `make preflight`: 78 tests plus benchmark drift/gate, locks, and all repository checks passed; PR #5 CI and independent review approved |
| 02 — Data Factory and trajectory pilot | Complete | PR #6 passed independent review, CI, GitGuardian, and Sol integration review; squash merged as `f45b1ea` |
| 03A0 — Fast/Slow architecture gate | Complete | PR #7 passed independent review, CI, and GitGuardian; squash merged as `54afcb8` |
| 03A1-H — deterministic evaluation harness | In progress | Activated from clean synchronized `main` at `54afcb8`; merged-main baseline `make preflight` passed |

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

### 2026-08-23 — Sol-governed delegation and merge workflow

- Human decision: the user delegated subagent selection and routine Git integration to the root Sol orchestrator.
- Transition evidence: Sol reviewed Phase 01A's complete diff and independent-review artifact, created PR #3, observed `phase-gate` and GitGuardian pass, and squash merged it to `main` as `f7f3cf7` without requiring a separate user PR review.
- Delegation policy: Sol may assign bounded implementer, reviewer, explorer, or fast-worker tasks when useful; a separate user authorization for each subagent is no longer required.
- Review policy: independent reviewers provide findings and recommendations for material changes, while Sol reconciles the evidence and owns the final approve or request-changes decision.
- Git policy: after a phase or bounded repository change is approved, Sol may create the branch, commit, push, open the PR, and squash merge after required gates pass without asking the user to review the PR.
- Cleanup boundary: deleting a fully merged short-lived branch is routine only after Sol confirms a clean worktree, a pushed branch, a merged PR, and no unique unpushed work; deleting unmerged work remains destructive and user-gated.
- Preserved human gates: new phases and scope expansion still require user approval, as do deployment, release publication, real external contact, credential use, destructive operations, force-push, and shared-history rewrites.
- Initial independent review: Request Changes because reusable prompts retained the old per-delegation user gate and merged-branch deletion was not distinguished from destructive branch deletion.
- Remediation: aligned root and subagent prompts with Sol-governed delegation, kept all Git publication operations prohibited for subagents, and limited automatic branch cleanup to confirmed merged/recoverable short-lived branches.
- Final independent rereview: Approve with no unresolved finding. Durable details are in `harness/code_review/sol-governed-agent-workflow.md`.
- Verification note: a restricted-sandbox `make preflight` attempt failed only because uv could not read `/Users/edison/.cache/uv/sdists-v9/.git`; rerunning with extended read access passed Ruff, mypy, 26 tests, contract drift, TypeScript, layout, locks, compile, and Compose.
- Final Sol verification after the durable review artifact was added: `make preflight` passed again with 26 tests and every repository-native gate.

### 2026-08-23 — Phase 01B activation and red gate

- Human gate: the user explicitly requested the next task and authorized its completion; Phase 01B simulator breadth and benchmark is the only active implementation phase.
- Frozen scope: 16 versioned scenario families, two deterministic fictional-Provider configurations, 32 scenarios, an allowlisted Safe Observation, family/entity-safe split manifest, scripted oracle, deterministic ceiling report, and adversarial environment checks.
- Preserved boundary: Phase 02 trajectories/data factory, Qwen/LFM work, services, Temporal, external channels, and UI remain excluded.
- Red architecture check: `runtime/.venv/bin/pytest -q tests/contract/test_phase_01b_architecture.py` produced one expected failure and one pass because `runtime/packages/agent_core/pyproject.toml` did not yet exist.
- Environment note: the equivalent uv command was initially blocked from the external uv cache by the sandbox; escalation was rejected by the system approval/usage limit. The repository's existing `.venv` supplied the red evidence without dependency changes.
- Delegation: Sol froze interfaces and assigned non-overlapping `agent_core` and Provider-environment implementation slices; subagents have no commit, publication, review-submission, or merge authority.

### 2026-08-23 — Phase 01B implementation and initial review

- Implemented a contracts-only `agent_core` package with an explicit Safe Observation allowlist and a scripted oracle that handles clarification, disclosure refusal, stale approval, transfer, missing confirmation Evidence, offer constraints, and the three supported business-action families.
- Implemented 16 versioned data-defined scenario families over two deterministic fictional-Provider configurations, yielding 32 scenarios through one environment engine.
- Added deterministic family/entity split generation with 10 train, 3 development, and 3 test families; both configuration derivatives of each family remain together.
- Added the benchmark composition CLI, committed split/ceiling artifacts, structural leakage scan, report fingerprints, and `make benchmark` / `make benchmark-check` gates.
- Integration red evidence: the first composed suite produced 40 passes and 2 failures because the oracle accepted the unsupported public change `account_cancellation`. The oracle action allowlist remediation brought the focused suite to 45 passes.
- Initial independent decision: Request Changes. Four P1 findings showed that caller Evidence could be omitted, the aggregate gate did not hard-require 16 families/two configurations, conflicting family/entity derivatives were order-dependent, and version changes did not affect identities/fingerprints.
- Root review additionally rejected Provider messages that copied private family descriptions because structural key scanning alone does not prevent semantic evaluator leakage.
- Remediation: completion Evidence is now bound and returned only by the Provider environment; the caller has no Evidence-reference field. The hard gate includes exact breadth and split counts; split generation rejects family/entity conflicts before assignment; family/config versions enter scenario identity, manifest hash, report rows, and report fingerprint; public messages use factual Provider-facing text rather than evaluator descriptions.
- Post-remediation focused suite: 52 passed.
- Post-remediation local equivalent full gate: Ruff format checked 27 files; Ruff lint passed; mypy passed on 18 source files; pytest passed 78 tests; contract drift and TypeScript compile passed; pnpm frozen offline lock passed; layout, Python compile, Compose, diff checks, and benchmark artifact/gate checks passed.
- `uv lock --project runtime --check` remains unverified locally because the sandbox cannot read the external uv cache and the system rejected escalation after its approval/usage limit was reached. The workspace-only lock entry was updated explicitly; CI must supply the authoritative uv lock check before merge.
- Independent rereview: Approve with no unresolved blocking finding. The reviewer reran 59 focused tests, the benchmark artifact check, Ruff, mypy, layout, and diff checks. Durable findings and remediation are recorded in `harness/code_review/phase-01b.md`.
- First authoritative `make preflight` after permissions were restored reached pytest and failed during collection because uv selected `runtime/` as the pytest root, so the repository-root `scripts` namespace was not importable. This was a test-runner path configuration failure, not a passing check.
- Remediation: set pytest's explicit repository-root `pythonpath` to `..` in `runtime/pyproject.toml`; the complete authoritative gate must be rerun before publication.
- The first remediation used the wrong relative base and the second `make preflight` failed at the same collection point. A read-only pytest probe confirmed `rootdir` is the repository root, so the setting was corrected from `..` to `.`; no test was reported as passing during either failed attempt.
- The third `make preflight` exposed the actual cause: pytest launched from the repository root never auto-discovered the nested `runtime/pyproject.toml`, so neither path value had been active. The Makefile now passes `-c runtime/pyproject.toml` explicitly and the configured `pythonpath` is restored to `..`, relative to the runtime config root. The authoritative gate must still pass after this runner fix.
- Focused runner verification after the explicit-config fix: `uv run --project runtime --all-packages pytest -c runtime/pyproject.toml -q` passed 78 tests.
- Final authoritative `make preflight`: passed. Ruff format checked 27 files; Ruff lint passed; mypy passed on 18 source files; pytest passed 78 tests; contract drift, TypeScript, benchmark artifact/gate, layout, uv lock (27 resolved packages), pnpm frozen offline lock, Python compile, and Docker Compose checks all passed.
- Final narrow independent review of the pytest runner fix: Approve. The reviewer confirmed the explicit runtime config collects all 78 intended suites, does not narrow discovery, and that the failure/remediation evidence is accurately recorded.
- PR #5 publication gate: GitHub `phase-gate` passed in 33 seconds and GitGuardian Security Checks passed. The PR remained mergeable with no unresolved review finding.
- Final Sol decision: Approve for squash merge. The complete PR diff, formal local preflight, independent review/rereview, generated artifact gate, dependency boundary, and CI evidence satisfy the Phase 01B contract.

### 2026-08-23 — Phase 02 activation and preflight

- Human gate: the user explicitly authorized Phase 02 Data Factory and trajectory pilot through independent review, CI, and squash merge.
- Base: clean synchronized `main` commit `0d05ab2`; active branch `feat/phase-02-data-factory`.
- Frozen scope: one-turn normalized schema, inherited Phase 01B family/entity/Provider splits, deterministic rollout/export, hard provenance/license/PII/deduplication/leakage/rejection checks, 128 accepted records, eight quarantine probes, cost/quality report, annotation guide, and a pending-human review sample.
- Preserved boundary: no teacher/model API calls, Qwen/LFM work, training, learned evaluation, services, Temporal, external channels, or UI.
- Baseline `make preflight`: passed before implementation. Ruff format checked 27 files; Ruff lint and mypy passed; pytest passed 78 tests; contract and benchmark drift checks, TypeScript, layout, runtime uv lock, pnpm frozen offline lock, Python compile, and Docker Compose configuration all passed.
- Red architecture evidence: the first uv-focused command was blocked by the sandbox reading `/Users/edison/.cache/uv/sdists-v9/.git`; the repository's existing runtime virtual environment then ran `tests/contract/test_phase_02_architecture.py` and produced two expected failures plus one pass because `ml/pyproject.toml` and the Data Factory source package did not yet exist.
- Red artifact evidence: `runtime/.venv/bin/pytest -c runtime/pyproject.toml tests/integration/test_phase_02_artifacts.py -q` produced two expected failures because the normalized schema and review-sample artifacts did not yet exist.

### 2026-08-23 — Phase 02 independent-review remediation

- Initial independent decision: Request Changes. The reviewer found that the cross-split fingerprint was not a frozen lexical normalization and omitted response text, while report audit values were literal declarations rather than derived evidence.
- Remediation: public-content fingerprints now remove opaque identifiers and normalize Unicode, case, whitespace, and punctuation before hashing; assistant response text is included. A non-byte-identical cross-split case/whitespace/punctuation probe now collides with an existing train fingerprint and is quarantined. The check is documented as a lexical heuristic, not embedding or semantic equivalence.
- Remediation: report provenance, accepted safety/dedup/leakage counts, quarantine reasons, external calls/tokens/cost, and automated status now derive from accepted/quarantined records and generator snapshots. A regression mutating source and external usage produces incomplete provenance, non-zero usage, and `automated_audit_status=failed`.
- Remediation cleanup: removed only the run-created root scratch files `findings.md`, `task_plan.md`, and `progress.md`.
- Durable review status: `harness/code_review/phase-02.md` records the findings and remediation; independent rereview remains pending.
- Remediation verification: `make preflight` passed with runtime Ruff format on 29 paths, ML Ruff format on 5 paths, both Ruff lint checks, runtime mypy on 18 source files, ML mypy on 4 source files, 83 runtime tests, 11 ML tests, contract drift, TypeScript, Phase 01B benchmark, Phase 02 artifact drift, layout, runtime and ML uv locks (27 and 21 packages), frozen offline pnpm lock, script compilation, and Docker Compose configuration.
- Pilot evidence after regeneration: `make data-pilot` reported 128 accepted and 8 quarantined candidates, inherited 80/24/24 splits, zero external calls/tokens/cost, 100% derived provenance completeness, `automated_audit_status=passed`, `human_review_status=pending_human`, and `training_ready=false`; `make data-pilot-check` passed.

### 2026-08-23 — Phase 02 second-rereview remediation

- Second independent rereview decision: Request Changes. Quarantine usage accounting lost raw generator snapshot usage whenever a candidate failed complete trajectory validation, such as missing source provenance.
- Remediation: raw usage accounting now defensively reads only correctly typed `generation.snapshots`; missing or malformed surrounding provenance cannot erase independently available external calls, token counts, or cost. A regression deletes `source`, records one external call, nine input tokens, and non-zero cost, and proves `missing_provenance` quarantine, retained audit usage, and `automated_audit_status=failed`.
- Regeneration and verification: regenerated Phase 02 artifacts and ran `make preflight`, which passed both Ruff checks, both mypy checks, 83 runtime tests, 12 ML tests, contract/TypeScript/Phase 01B/Phase 02 artifact gates, layout, both uv locks, offline pnpm lock, script compilation, Docker Compose configuration, and diff checks.
- Durable review status: `harness/code_review/phase-02.md` remains pending independent rereview; this remediation is not an approval.

### 2026-08-23 — Phase 02 local gate closeout

- Final independent rereview: Approve with no unresolved local blocking finding. The durable record is `harness/code_review/phase-02.md`.
- Final local evidence: `make preflight` passed with 83 runtime tests and 12 ML tests; both Ruff and mypy gates, contract and TypeScript checks, Phase 01B benchmark and Phase 02 artifact drift gates, layout, both uv locks, offline pnpm lock, script compilation, Docker Compose configuration, and diff checks passed.
- Pilot boundary remains explicit: the review sample is `pending_human`, `training_ready=false`, external model calls/tokens/cost are zero, and Phase 03 is inactive.
- Integration status at local closeout: PR publication, CI, GitGuardian, Sol integration review, and squash merge had not yet run. Do not activate Phase 03 until Phase 02 is merged and the user provides a new explicit gate.

### 2026-08-23 — Phase 02 PR #6 initial publication gate

- Live PR state: PR #6 head `9fd33e0`, base `0d05ab2`, open, non-draft, `MERGEABLE`, and `CLEAN`.
- Initial publication checks: GitHub `phase-gate` succeeded in 41 seconds and GitGuardian succeeded.
- Sol final integration decision: Approve for squash merge after the final docs-only evidence commit and its CI rerun. Sol reviewed the complete local and staged diff, final local `make preflight`, independent review evidence, and live PR state.
- Remaining integration work: commit the final evidence-only documentation change, observe its CI rerun, then squash merge. The human review sample remains `pending_human`, `training_ready=false`, and Phase 03 remains inactive.

### 2026-08-23 — Phase 02 integration completion

- PR #6's final documentation evidence commit passed the required repository checks and the bounded change was squash merged to `main` as `f45b1ea` (`feat(data): add phase 02 trajectory pilot (#6)`).
- Local `main` was clean and synchronized with `origin/main`; the short-lived Phase 02 branch was cleaned after confirming no unique unpushed work.
- The committed pilot boundary did not change: `human_review_status=pending_human`, `training_ready=false`, and the one-turn records are Data Factory regression evidence rather than a Qwen training corpus.

### 2026-08-23 — Phase 03A0 activation and preflight

- Human gate: the user explicitly authorized the Fast/Slow architecture revision and executable acceptance criteria before any Phase 03A1 implementation or model work.
- Base: clean synchronized `main` commit `f45b1ea`; active branch `docs/phase-03a0-fast-slow-architecture`.
- Frozen scope: deterministic Router, model-external Case Context Snapshot, separate Fast/Slow views, planning-basis and stale-result semantics, serialized Case writes/side effects, capability/approval/execution/completion ownership, Qwen training boundary, and the next implementation gate.
- Preserved boundary: no runtime contract/source, model call/download, training, teacher/data expansion, API, PostgreSQL, Temporal, product Agent, UI, MCP, Gmail, LiveKit, telephony, real Provider contact, credentials, or consumer PII.
- Baseline `make preflight`: passed before Phase 03A0 deliverable edits. Ruff format/lint and mypy passed for runtime and ML; pytest passed 83 runtime and 12 ML tests; contract/TypeScript, Phase 01B benchmark, Phase 02 artifact, layout, runtime/ML lock, offline pnpm lock, script compile, and Docker Compose checks passed.

### 2026-08-23 — Phase 03A0 local gate closeout

- Architecture decision: froze separate Fast/Slow interfaces behind a deterministic Router and model-external Case Context Snapshot; one authority each owns routing, strategy proposal, turn proposal, policy, approval, capability execution, Case state, and final completion.
- Router remediation: independent review initially requested changes because completion, Evidence, approval, and Slow triggers overlapped. The final top-to-bottom algorithm emits exactly one outcome: `terminal`, `verify_only`, `wait_for_approval`, `slow_refresh`, `fast_now_and_slow_refresh`, or `fast_now`.
- Boundary remediation: added drift coverage for Pine's public self-description versus ProxyLoop decisions, Fast/Slow view exclusions, advisory Fast `reasoner_request`, executor revalidation, evaluation-before-training, Router precedence, disabled Fast Action Intent, and bounded Qwen targets.
- Independent rereview: Approve with no remaining Critical or Important finding. Durable findings and remediation are recorded in `harness/code_review/phase-03a0.md`.
- Focused evidence: `python3 -m pytest -q tests/contract/test_phase_03a0_architecture.py` passed 11 tests; `make check-layout` and `git diff --check` passed.
- Formal-gate corrections: the first `make preflight` stopped at Ruff formatting for the new test; after formatting, a sandboxed rerun was blocked from the existing uv cache; the first extended-access rerun then exposed Ruff import/line-length lint findings. These attempts were not reported as passes. The test was mechanically formatted and lint-corrected before the final run.
- Final authoritative `make preflight`: passed. Runtime and ML Ruff format/lint passed; runtime mypy passed on 18 files and ML mypy on 4; runtime/contract/integration pytest passed 94 tests and ML pytest passed 12; contract and TypeScript drift, Phase 01B benchmark, Phase 02 artifact, layout, runtime/ML uv locks, frozen offline pnpm install, script compilation, Docker Compose configuration, and diff checks all passed.
- Preserved boundary: no runtime canonical contract/schema/type, dataset, dependency/lockfile, model call/download, training, product service, API, Temporal, UI, MCP, email, telephony, credential, PII, or real-Provider implementation was changed or activated.
- Publication status: local gate approved; PR, CI, GitGuardian, final Sol integration decision, squash merge, and merged-branch cleanup remain pending.

### 2026-08-23 — Phase 03A0 PR #7 initial publication gate

- Live PR state at head `a768c30`: open, non-draft, `MERGEABLE`, and `CLEAN` against `main` at `f45b1ea`.
- Initial publication checks: GitHub `phase-gate` passed in 37 seconds and GitGuardian Security Checks passed in 1 second.
- Sol reviewed the complete 18-file PR diff, clean local worktree, independent review/rereview evidence, final local `make preflight`, required artifacts, scope boundary, and live merge state. Final decision: Approve for squash merge after this docs-only evidence commit passes its CI rerun.
- Remaining integration work: push this evidence-only commit, observe the final CI/GitGuardian rerun, then squash merge and clean the fully merged short-lived branch. Phase 03A1 and every model call/download, benchmark, training, data expansion, product service, channel, and UI remain inactive.

### 2026-08-23 — Phase 03A0 integration completion

- PR #7's final evidence commit passed `phase-gate` and GitGuardian and was squash merged to `main` as `54afcb8` (`docs(architecture): freeze fast/slow orchestration (#7)`).
- Local `main` was clean and synchronized with `origin/main`; the short-lived Phase 03A0 branch was cleaned after confirming no unique unpushed work.
- Post-merge `make preflight` passed with 94 runtime/contract/integration tests and 12 ML tests plus every repository-native gate.

### 2026-08-23 — Phase 03A1 Harness activation and preflight

- Human gate: the user explicitly authorized Phase 03A1 as two sequential pull requests and requested Luna xhigh implementation under Sol direction plus independent Terra high review.
- Base: clean synchronized `main` commit `54afcb8`; active branch: `feat/phase-03a1-harness`.
- Baseline `make preflight`: passed before deliverable edits with 94 runtime/contract/integration tests, 12 ML tests, and every format, lint, type, contract/type drift, Phase 01B/02 artifact, layout, lock, offline install, compile, and Compose gate.
- Frozen Harness boundary: deterministic contracts, Case coordination, Router, model views/interfaces, stale-result/CAS, simulator-only capabilities, multi-turn episodes, frozen manifests, scripted-oracle ceiling, and artifact drift evidence only.
- Preserved boundary: no Qwen/frontier dependency, download, API/model call, prompt tuning, training, generated-data expansion, FastAPI, PostgreSQL, Temporal, product Agent, channel, UI, real Provider, credential, or consumer PII work.

### 2026-08-23 — Phase 03A1 Harness independent-review remediation

- Initial Terra decision: Request Changes. The review found two Critical and five Important issues: formal episodes bypassed the sole Executor, adapters could mutate before Evidence validation, episode artifacts leaked oracle labels, Provider-held-out eligibility was nominal, coordinator CAS/Slow binding was incomplete, bounded Fast filtering was language-specific, and approval routing trusted a caller boolean.
- First remediation routed every formal episode through prepared-Evidence atomic execution, bound Evidence/idempotency/offer/approval/material terms, removed complete-episode label leakage, added executable eligibility fields, serialized snapshot CAS/latest reroute, strict Slow validation, a fixed Fast template, and latest-visible-event approval derivation.
- First focused rereview: Request Changes with no Critical and two Important findings. Held-out scenarios still reached Scripted Slow despite eligibility metadata, and Executor idempotency was not atomic across concurrent calls.
- Final remediation made manifest eligibility an execution selector before Slow request construction, added a zero-ineligible-Slow ceiling gate, serialized the complete Executor critical section with `RLock`, added a Barrier-aligned concurrent duplicate regression, converted adapter evidence to canonical ModelTrace records, and tested all eight material Planning Basis mutations.
- Final authoritative `make preflight`: passed with 128 runtime/contract/integration tests and 12 ML tests plus all format, lint, mypy, schema/type drift, Phase 01B/02/03A1 artifact, layout, lock, offline install, compile, Compose, and diff gates.
- Final independent Terra rereview: Approve with no unresolved Critical or Important finding. Terra independently reran the same complete `make preflight` successfully. Durable findings and remediation are recorded in `harness/code_review/phase-03a1-harness.md`.
- Publication status: local gate approved. PR, remote CI, GitGuardian, Sol integration decision, squash merge, cleanup, and post-merge verification remain pending; 03A1-B has not started.
