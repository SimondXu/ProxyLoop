# ProxyLoop Build Log

This is the immutable historical execution log through the Harness v2 migration. New bounded changes record concise evidence in `harness/log/<change>.md`; do not append here by default. Read this file only for a named historical claim or audit.

## Phase Status

| Phase | Status | Last evidence |
|---|---|---|
| 00A — repository foundation | Complete | Initial repository layout validated and published before this harness initialization |
| 00B — canonical contracts | Complete | `make preflight`: 17 tests plus format, lint, type, generation, drift, TypeScript, layout, locks, compile, and Compose passed |
| 01A — deterministic Provider loop | Complete | Independent `make preflight`: 26 tests plus the complete repository gate passed; matching-forgery and no-mutation probes were rejected |
| 01B — simulator breadth and benchmark | Complete | `make preflight`: 78 tests plus benchmark drift/gate, locks, and all repository checks passed; PR #5 CI and independent review approved |
| 02 — Data Factory and trajectory pilot | Complete | PR #6 passed independent review, CI, GitGuardian, and Sol integration review; squash merged as `f45b1ea` |
| 03A0 — Fast/Slow architecture gate | Complete | PR #7 passed independent review, CI, and GitGuardian; squash merged as `54afcb8` |
| 03A1-H — deterministic evaluation harness | Complete | Squash merged through PR #8 as `e08c9b6` |
| 03A1-B — untuned hosted baselines | Complete | PR #9 passed independent review and CI/GitGuardian gates |
| 03A1-E — leakage-safe evaluation erratum | Complete — Provider blocked | PR #10 passed independent review and CI/GitGuardian with terminal Provider blocker preserved |
| 03A1-R/V — hosted reliability and validity | Complete | PR #11 passed CI/GitGuardian and squash merged as `e501e0f` |
| 03B — Qwen QLoRA smoke | Complete — No-Go | PR #15 passed CI/GitGuardian and squash merged as `f441335`; final decision `NO_GO_STOP_PHASE03B` |
| 04A — thin agent runtime | Complete | PR #12 squash merged as `75974da` after independent review and repository gates |
| 04B — model-backed thin runtime | Complete | PR #13 passed CI/GitGuardian and squash merged as `6daa1bc` |
| Current implementation phase | None active | A new explicit human gate is required before implementation, evaluation, training, deployment, or release work |

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

### 2026-08-23 — Phase 03A1 Harness PR #8 initial publication gate

- PR #8 at head `5f8d609` is open, non-draft, `MERGEABLE`, and `CLEAN` against `main`; its 35-file diff matches the reviewed local commit.
- Initial publication checks passed: GitHub `phase-gate` in 46 seconds and GitGuardian Security Checks in 1 second.
- Sol reviewed the final head, complete file list and diff statistics, local and independent preflight evidence, final Terra approval, generated artifacts, authority/held-out boundaries, and prohibited scope. Final decision: Approve for squash merge after this evidence-only commit passes its CI rerun.
- Remaining integration work: push this build-log evidence, observe the final CI/GitGuardian rerun, then squash merge and clean the fully merged short-lived branch. Phase 03A1-B has not started; no model download/call, training, data expansion, product service, channel, or UI is authorized by this gate.

### 2026-08-23 — Phase 03A1 Harness integration completion

- PR #8's final evidence commit passed `phase-gate` and GitGuardian and was squash merged to `main` as `e08c9b6` (`feat(agent): add multi-turn evaluation harness (#8)`).
- Local `main` was clean and synchronized with `origin/main`; the short-lived Harness branch was cleaned after confirming no unique unpushed work.
- Post-merge `make preflight` passed with 128 runtime/contract/integration tests, 12 ML tests, and every repository-native gate.
- The final independent Terra decision remained Approve with no unresolved Critical or Important finding.

### 2026-08-23 — Phase 03A1 Baselines activation and preflight

- Human gate: the user explicitly authorized the second sequential Phase 03A1 pull request and requested Luna xhigh implementation under Sol direction plus independent Terra high review.
- Base: clean synchronized `main` commit `e08c9b6`; active branch: `experiment/phase-03a1-baselines`.
- Local target: Apple M4 Pro with 48 GB unified memory and sufficient free disk for the approximately 2.28 GB MLX 4-bit Qwen checkpoint. Hardware serial and UUID are excluded from evidence.
- Frozen Fast candidate: official Apache-2.0 `Qwen/Qwen3-4B-Instruct-2507` lineage, using the derived `mlx-community/Qwen3-4B-Instruct-2507-4bit` checkpoint only with explicit `quantized_untuned` labeling and pinned provenance.
- Frozen frontier candidate: `gpt-5.6-sol` through the Responses API. Official preflight pricing observed was $4/M input and $20/M output tokens; an explicit run ceiling is required before calls.
- Credential observation: no supported frontier API key is present. Missing credentials must remain a truthful not-run blocker; the repository will not recover credentials from unrelated application state.
- Preserved boundary: no tuning, training, data expansion, serving, product Agent, channel, UI, real Provider, credential persistence, PII, deployment, or Phase 03B work.

### 2026-08-23 — Phase 03A1 Baselines local implementation evidence

- Red architecture evidence: the first focused run of `tests/contract/test_phase_03a1_baselines_architecture.py` produced three intended failures because the ML-only evaluation surface, offline Make gate, and frozen Baselines phase contract did not yet exist.
- Dependency isolation: `mlx-lm==0.31.3` on Apple arm64 and `openai==2.51.0` are optional ML evaluation dependencies only. The runtime project and lock remain free of model SDKs; imports are lazy and deterministic CI does not download or call a model.
- Frozen checkpoint provenance: local inference used `mlx-community/Qwen3-4B-Instruct-2507-4bit` revision `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b`, derived from Apache-2.0 `Qwen/Qwen3-4B-Instruct-2507` revision `cdbee75f17c01a7cc42f958dc650907174af0554`, and is labeled `quantized_untuned`.
- An initial adapter preflight produced 0/32 schema-valid outputs because it incorrectly asked the model to invent infrastructure-owned UUIDs, timestamps, pins, and the full nested canonical result without exposing the exact semantic schema. That run is invalidated and is not represented as model-quality evidence.
- Interface correction: Fast and Slow models now emit strict semantic proposals only. Deterministic compilers bind current IDs, timestamps, revisions, pins, capability versions, offer terms, and inert Action Intent proposals before the existing coordinator and Executor validate them. The compilers reject invented constraint, disclosure, capability, and offer references and do not repair semantic choices.
- Final attested local Qwen run: 32/32 calls and 32/32 strict schemas completed over the frozen episodes; input/output use was 63,082/7,082 tokens, latency p50/p90 was 5,778/6,120 ms, and local API cost was zero. Four outputs were valid evidence-safe non-completions; 28 proposed an unsupported completion candidate. The Harness classified all 28 failures by development/family-entity-held-out/safety, development/provider-held-out, safety flag, `fast_now` route, and succeeded-adapter slices. `action_intent` remained null, no capability executed, and no candidate became authoritative completion.
- True Slow-off ablation: all 32 mandatory Slow routes ended as typed `slow_unavailable` valid non-completions; Fast did not bypass the Router and no model call occurred.
- Frontier safety gate: the two hosted conditions remain `not_run_missing_credentials`; no hosted request, token, or cost has occurred. The runner is frozen to zero retries, 8,192 input and 4,096 output tokens per call, 32 hosted Slow calls plus 64 frontier-reference calls, and a conservative maximum of $11.010048. It requires both `OPENAI_API_KEY` in the process environment and an explicit command-line approval at or above that ceiling.
- Initial independent Terra review: Request Changes with one Critical and four Important findings. The OpenAI SDK retained its default two retries; post-dispatch exceptions could be mislabeled as not-run/zero-cost; live scenarios were not rebound to frozen Harness artifacts; Qwen revision strings were CLI declarations rather than file attestations; and the offline checker could not replay prompts, semantic outputs, calls, or cost.
- Review remediation: the OpenAI client now sets `max_retries=0`; an attempted request without auditable usage becomes a terminal failed condition with a counted `HostedCallEvidence`, `actual_cost_unknown`, and incomplete cost accounting. Every model command regenerates and compares the live manifest/episode/ceiling fingerprints before loading a checkpoint or making a call.
- Provenance and replay remediation: the runner SHA-256 attests the actual 2.263 GB model, tokenizer set, and chat template against frozen fingerprints; CLI revision declarations were removed. The offline checker rebuilds frozen prompts, recompiles recorded Fast/Slow semantic outputs, validates output and prompt fingerprints, and checks hosted response IDs, exact model metadata, per-call usage, call counts, actual cost, and conservative maxima. Tampered prompt, cost ceiling, fixture drift, missing calls, checkpoint mutation, SDK retry, and attempted-call regressions are covered.
- Final local verification before rereview: `make preflight` passed with 135 runtime/contract/integration tests and 38 ML tests plus every format, lint, mypy, contract/type drift, Phase 01B/02/03A1 Harness/Baselines artifact, layout, lock, offline pnpm, compile, Compose, and diff gate. A prior attempt was not reported as passing: it exposed one stale Phase 03A0 drift assertion, which was updated to recognize the merged Harness commit before the successful rerun.

### 2026-08-23 — Phase 03A1 Baselines second-rereview remediation

- Second Terra rereview decision: Request Changes with no Critical and two Important findings. The first provider attempt with unknown actual cost stopped only its current condition, so the runner could still start the frontier-reference condition; failed attempted-call artifacts were also skipped by the offline replay gate.
- Global budget remediation: any started hosted call whose actual cost cannot be audited now makes the current condition terminally failed. The ordered hosted runner converts the later frontier-reference condition to `not_run_budget_rejected` with zero calls and zero episodes, rather than making another external request. A regression uses two injected clients and proves that the first client is called once while the second is never called.
- Failure-evidence remediation: offline replay now rebuilds the failed Slow or Fast request, validates its prompt and schema fingerprints, requires exactly one final unknown-cost attempt, reconciles model-call counts and known costs, rejects fabricated response metadata for provider-dispatch failure, and verifies that no later hosted condition ran. Refingerprinted tampering of the attempted-call count or unknown-cost evidence fails the artifact gate.
- Final authoritative verification after this remediation: `make preflight` passed with 135 runtime/contract/integration tests and 42 ML tests plus every repository-native format, lint, mypy, contract/type drift, Phase 01B/02/03A1 Harness/Baselines artifact, layout, lock, offline pnpm, compile, Compose, and diff gate. An earlier broad `pytest` invocation used the wrong root/config and failed collection; it is not reported as a repository test failure or pass. The repository-native ML command and complete preflight both passed.
- Final independent Terra rereview: Approve for the current implementation scope with no unresolved Critical or Important finding. The durable record is `harness/code_review/phase-03a1-baselines.md`. Terra independently reran `make preflight` successfully with 135 runtime/contract/integration tests and 42 ML tests.
- The approval does not close Phase 03A1: no hosted request has been made, both hosted conditions in the committed artifact remain truthfully `not_run_missing_credentials`, and `phase_completion_ready=false`.

### 2026-08-24 — Phase 03A1 Terra reference decision and compatibility probe

- Human decision: use `gpt-5.6-terra` through the user-provided `https://29qg.com/v1/chat/completions` compatibility endpoint as the only learned frontier reference. Sol is removed from the Phase 03A1 model matrix; it remains only the Codex root-orchestrator name elsewhere in the repository.
- Secret handling: the user-pasted credential was not copied into source, logs, or a tracked file. The ignored local `.env` was read only into the probe process and its mode was tightened to `0600`; credential values are excluded from all evidence.
- First probe reached the proxy but was rejected before inference with HTTP 403 because the remaining quota was `$0.000016` and the provider required `$0.001564` pre-consumption. No model result or usage was recorded from that attempt.
- Successful probe after the user adjusted quota: HTTP 200 from `gpt-5.6-terra-2026-07-09`; strict JSON Schema returned `ok=true` and `label=terra-probe`; usage was 63 prompt, 20 completion, and 83 total tokens. Provider latency metadata reported 422 ms user-visible TTFT and 645 ms total duration; end-to-end curl time was 2.640 seconds.
- A proposed one-call repository-adapter smoke test was rejected before process creation because it would send a frozen fictional evaluation payload to the third-party endpoint without a payload-specific external-disclosure authorization. No request or cost occurred. The runner will not retry or work around this gate; explicit user approval is required before any Phase 03A1 episode leaves the machine.
- Scope consequence: the previous independent approval covered the Sol/Responses implementation and is superseded. The Terra/Chat Completions adapter, conservative proxy-cost accounting, real hosted results, and final artifacts require fresh independent review before merge.

### 2026-08-24 — Phase 03A1 complete untuned Terra-backed run

- Repository-adapter smoke after explicit payload-disclosure authorization: one frozen FastModelView passed the SDK Chat Completions parse seam and canonical Fast compiler. The proxy returned `gpt-5.6-terra-2026-07-09`; usage was 1,868 prompt and 96 completion tokens, adapter latency was 3,596 ms, `action_intent=null`, and the completion status was `not_done`.
- Full execution completed without a terminal provider or quota failure. The offline artifact/replay gate passed and the report records all five conditions with `phase_completion_ready=true`. This flag means every experiment condition ran and is reproducible; it is not a model-quality pass.
- Qwen Fast plus Terra Slow: 32/32 episodes evaluated. Terra Slow made 32 hosted calls; only four Slow proposals passed canonical validation and therefore triggered four local Qwen Fast calls. All four combined outputs were schema-valid but none was end-to-end valid; all four Qwen outputs proposed unsupported completion candidates. The other 28 Slow outputs failed before Fast: 19 invented a preference reference and nine bound an offer to a non-offer capability. The condition recorded 101,002 input and 22,083 output tokens across both model seams, p50/p90 episode latency 10,692/17,541 ms, and `$0.783092` conservative usage-accounted cost.
- Terra reference: 32/32 episodes evaluated with 32 Terra Slow calls and three subsequent Terra Fast calls. Three combined outputs were schema-valid, none was end-to-end valid, and no Terra Fast output proposed false completion. The 29 rejected Slow outputs comprised 23 invented preference references and six non-offer capabilities bound to offers. The three canonical pairs still failed deterministic approval/capability/provider-outcome checks. The condition recorded 98,592 input and 20,131 output tokens, p50/p90 episode latency 10,089/12,244 ms, and `$0.796988` conservative usage-accounted cost.
- Safety result: zero evaluator/private leakage, zero authoritative false completion, and no model bypass of Router, policy, approval, Executor, Evidence, or Verifier. Qwen with the frozen reference strategy remains 4/32 valid safe non-completions with 28 unsupported completion candidates; true Slow-off remains 32/32 safe typed non-completions.
- Cost interpretation: the proxy returns usage but no invoice field. `$1.580080` is the sum of actual returned token usage multiplied by the frozen conservative `$4/M` input and `$20/M` output quota-accounting rates; it is not asserted to equal the provider invoice. The approved theoretical maximum remains `$11.010048`, while the user independently configured the provider-side account limit.
- Training conclusion is not yet authorized: observed failures justify reviewing semantic reference selection and model suitability, but no SFT, prompt retuning on held-out episodes, data expansion, serving, or Phase 03B work begins in this phase.

### 2026-08-24 — Phase 03A1 Terra-backed final independent review

- Fresh Terra review initially returned Request Changes with no Critical and one Important finding: the report fingerprint bound every run to a fixed `2026-08-23T00:00:00Z` generation time even though the full hosted run occurred on 2026-08-24.
- Remediation removed the fixed timestamp, records actual second-precision UTC report creation, validates the UTC `Z` schema, and adds a timestamp/fingerprint regression. The full-run artifact now records its final write time, `2026-08-24T05:24:05Z`, with a recomputed fingerprint.
- Root focused artifact verification passed with 10 tests. Root then ran the complete repository-native `make preflight`: 135 runtime/contract/integration tests and 43 ML tests passed, together with all format, lint, mypy, contract/type drift, artifact replay, layout, lock, offline pnpm, compile, Compose, and diff gates.
- Final independent rereview: Approve with no unresolved Critical or Important finding. Terra independently ran the same 10 artifact tests and complete `make preflight` successfully and made no model/API request.
- Evidence boundary retained: the proxy's returned snapshot metadata is validated and explicit model-family remapping is rejected, but the repository does not independently prove the third-party proxy's hidden physical backend. Usage-accounted cost remains explicitly distinct from a provider invoice.

### 2026-08-24 — Phase 03A1 PR #9 CI environment remediation

- The first PR #9 `phase-gate` run failed at ML mypy because CI intentionally installs the default ML dependency set without the optional `evaluation` extra, while a static lazy-path `from openai import OpenAI` still required the absent SDK at type-check time. Local preflight had the extra installed and therefore did not expose the mismatch. GitGuardian passed.
- An isolated temporary ML environment created with the same default `uv sync --project ml --frozen` reproduced the exact `import-not-found` error on `openai_frontier.py`.
- Minimal remediation changed only the optional runtime import seam to `importlib.import_module("openai")`, matching the existing Qwen lazy-import boundary; CI remains free of model SDK installation and runtime packages remain unaffected. The architecture regression now asserts the dynamic import.
- The isolated CI-equivalent mypy command then passed. Thirteen Terra adapter tests and seven Baselines architecture tests also passed before the full repository gate was rerun.
- Root's complete post-remediation `make preflight` passed with 135 runtime/contract/integration and 43 ML tests plus every repository-native gate. Independent Terra rereview returned Approve with no new Critical or Important finding and independently passed the same full preflight without a hosted request.
- The repaired PR #9 then passed both GitHub `phase-gate` and GitGuardian. Repository status was closed to Phase 03A1 complete with no active implementation phase; Phase 03B remains explicitly inactive.
- Independent Terra review approved the status closeout with no Critical or Important finding and independently passed the full 135 + 43 preflight without a hosted request.

### 2026-08-24 — Phase 03A1-E evaluation erratum local gate

- Human gate and scope: the user approved a corrected second evaluation attempt
  and disclosure of the frozen fictional payloads to the configured 29qg
  endpoint. No training, data expansion, product Agent, channel, UI, deployment,
  or Phase 03B work was authorized.
- Evaluator correction: r2 separates Provider JSON, output schema, semantic
  compile, canonical binding, authorization/execution, Provider outcome, and
  end-to-end validity. Exact reference match is diagnostic. Model fixtures do
  not preload oracle ActionIntent or ApprovalRequest state, and consequential
  continuation remains exactly bound through Policy, Approval, Executor,
  Evidence, and Verifier.
- Fresh deterministic evidence: 32 disjoint r2 multi-turn episodes and the
  scripted ceiling passed with 32/32 end-to-end-valid outcomes, zero false
  authoritative completion, and zero leakage. Raw Fast/Slow outputs are bounded
  and semantically replayed through fake no-network adapters.
- Local untuned Qwen: 32/32 JSON/schema/canonical outputs; three safe
  non-completions and 29 unsupported completion candidates. Fast
  `action_intent` stayed null and no candidate became authoritative completion.
  Slow-off produced 32/32 typed `slow_unavailable` safe non-completions with zero
  model calls.
- Hosted terminal evidence: the first medium Slow request started but returned
  no auditable response or usage. R2 records one `failed_provider_call`, unknown
  actual cost, and incomplete accounting. The global abort prevented all three
  remaining hosted conditions from starting; each has zero calls and
  `not_run_budget_rejected`. No retry was issued.
- Post-dispatch version boundary: independent review found that the raw r2 report
  also attached a false `router_outcome_mismatch`. R2 remains immutable with
  source fingerprint `499b62b7e0a6e1148652dcaf1bdc6538a6893c1aaa4d2476b5680b603770afa6`.
  The separately versioned r3 report corrects attribution only by offline replay,
  binds the r2 fingerprint and source timestamp, preserves raw/call evidence,
  records source hosted calls=1, new external dispatches=0, offline replay
  conditions=4, evaluator version, and the executed Qwen output cap=512.
- Independent review history: the first Terra review requested changes for one
  Critical report-readiness integrity defect and two Important Qwen/Router
  attribution defects. A second review requested one Important timestamp fix.
  After Red/Green remediation and source-bound r3 derivation, final Terra
  decision was Approve with no unresolved Critical or Important finding. The
  durable record is `harness/code_review/phase-03a1-evaluation-erratum.md`.
- Focused final evidence: 25 r3/runner tests passed; r3 offline checker, Ruff,
  strict mypy, and `git diff --check` passed. The reviewer made no model/API call
  and did not read credentials.
- Final authoritative local `make preflight`: passed with 135 runtime/contract/
  integration tests and 89 ML tests. Runtime/ML Ruff and mypy, contract and
  TypeScript drift, Phase 01B/02/03A1-H/03A1-B/03A1-E artifact replay, layout,
  both uv locks, frozen offline pnpm, script compilation, Docker Compose, and
  diff gates all passed.
- Local outcome: Phase 03A1-E is approved for PR integration with an honest
  terminal Provider blocker; `phase_completion_ready=false`. This is sufficient
  for the phase's truthful-blocker acceptance criterion, but it is not a model
  matrix success and does not activate Phase 03B.

### 2026-08-24 — Phase 03A1-E PR #10 publication gate

- Initial PR state: PR #10 at head `f96f7f7`, base `f5c43d8`, open, non-draft,
  `MERGEABLE`, with a clean bounded 37-file phase diff.
- GitHub checks passed on the reviewed head: repository `phase-gate` in 54
  seconds and GitGuardian Security Checks in 1 second.
- Sol final integration review: Approve after the status/evidence-only closeout
  commit passes its CI rerun. Sol reviewed the full file scope, final local
  `make preflight`, r2/r3 source binding, terminal blocker semantics, independent
  Terra approval, and prohibited-scope boundary.
- Remaining integration work: push this closeout evidence, observe the final
  CI/GitGuardian rerun, then squash merge and clean the fully merged short-lived
  branch. Phase 03B remains inactive.

### 2026-08-24 — Phase 03A1-R activation and pre-Provider gate

- Human gate: after reviewing the merged Phase 03A1-E terminal Provider
  blocker, the user explicitly requested the recommended reliable Terra hosted
  baseline rerun. Scope remains evaluation evidence only; Phase 03B, training,
  data expansion, product services, database, real tools/Providers, deployment,
  channels, and UI remain inactive.
- Integrated base: clean synchronized `main` at `a91943c`; active branch
  `experiment/phase-03a1-hosted-rerun`.
- Frozen evidence boundary: r2 file SHA-256
  `dbfb88c72317046b587ca63142adf71cf0f9b27d4b8f6bcb56e071bf290506b3`
  and report fingerprint
  `499b62b7e0a6e1148652dcaf1bdc6538a6893c1aaa4d2476b5680b603770afa6`;
  r3 file SHA-256
  `c5ed4955bf598db2807a30aa1795fdf886f5b2cf6de2d27ec17541dc10bbcd72`
  and report fingerprint
  `a80e9f2677753c6efb7286706a60703d4d56472941ee88189b88833504477e6c`.
- Red evidence: the new architecture check initially produced the intended
  result, two failures and one pass, because the separate hosted-rerun module,
  command, artifact path, and Make gate did not exist.
- Minimal implementation: a new r4 module binds immutable r2/r3 sources, runs
  a fixed non-evaluation medium/high structured probe, records allowlisted
  error metadata, blocks the matrix after any failed probe, reuses the three
  authoritative r3 local conditions, executes only the four frozen hosted
  conditions, reconciles external dispatches/cost/readiness, and replays the
  nested matrix offline. Existing r2/r3 writers and files were not modified.
- Adapter safety: zero SDK retries remains frozen. Persisted error detail is
  limited to exception class, HTTP status, request ID, and Provider
  code/type/param. Arbitrary Provider messages, headers, request bodies,
  credentials, and raw exception representations are excluded.
- Focused remediation gate: 43 ML tests and 10 runtime architecture tests
  passed. Changed-file Ruff, `git diff --check`, and strict mypy over the new
  adapter/module/script passed.
- Broad offline gate: 138 runtime/contract/integration tests and 94 ML tests
  passed. Full ML format/lint and `git diff --check` passed. The existing
  Phase 03A1-E offline checker passed with the terminally blocked r2/r3 report.
- Provider credential gate: `.env` remains ignored and mode `0600`, but
  `PROXYLOOP_FRONTIER_API_KEY` is absent from both `.env` and the active process.
  The real probe command rejected before adapter construction with exit 2 and
  the explicit missing-credential message. No Phase 03A1-R external dispatch or
  cost occurred.
- Layout check is not reported as passed: it truthfully fails only because
  `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` cannot exist before
  the blocked Provider probe. Full `make preflight`, hosted matrix, review
  closeout, PR, CI/GitGuardian, and integration remain pending.
- Initial independent pre-Provider review: Request Changes with two Important
  findings and one Minor workflow finding. A response with valid usage but no
  response ID could fail before its terminal evidence was serialized; arbitrary
  Provider error messages could echo request/secret material; and pre-dispatch
  validation needed a source-only gate that did not require r4.
- Review remediation: missing response IDs now produce auditable
  `failed_invalid_response` evidence with retained usage/accounted cost and stop
  all follow-on probes; arbitrary Provider messages were removed from both
  evidence schemas; request-echo/multiple-secret and missing-ID regressions were
  added; and `hosted-rerun-source-check` now validates immutable sources,
  budget arithmetic, probe fingerprints, and the frozen execution contract
  without requiring r4. The probe report binds its execution-contract
  fingerprint so later code/dependency drift blocks the matrix.
- Second independent review: Request Changes with one Important finding. A
  matrix adapter's mutable `last_error` could lose an earlier known-cost
  failure when a later call succeeded. Remediation added append-only per-call
  error history with condition scope and 1-based call index, plus a regression
  proving a later success cannot overwrite `MissingResponseId`.
- Third independent review: Request Changes with one Important finding. The r4
  checker did not yet reconcile history rows against actual failed calls.
  Remediation added bidirectional `(scope, call_index)` reconciliation and
  refingerprinted deletion, wrong-index, duplicate, unknown-scope, and orphan
  rejection. Probe-embedded errors must also match global history.
- Final independent Terra decision: Approve with no unresolved Critical or
  Important finding. The durable pre-Provider review is
  `harness/code_review/phase-03a1-hosted-rerun-pre-provider.md`.
- Final pre-Provider offline evidence: 138 runtime/contract/integration tests
  and 100 ML tests passed. Full runtime/ML Ruff format and lint, strict mypy
  (25 runtime and 23 ML source files), diff checks, script compilation, Docker
  Compose config, both uv lock checks, frozen offline pnpm lock check, the Phase
  03A1-E source/replay check, and the Phase 03A1-R source-only gate passed.
  Immutable r2/r3 file hashes remain unchanged. Layout still fails only on the
  intentionally absent r4 artifact. No Provider call or cost occurred.

### 2026-08-24 — Phase 03A1-R hosted execution and terminal gate

- The user asked to finish the existing r4 path without further overengineering,
  confirmed the 29qg credential/base URL were present locally, and stated that
  Provider-side hard cost controls own spend. No cost cap or evaluation contract
  was widened.
- Local credential-format correction: `.env` contained colon-delimited
  `api:<secret>` and `base_url:<url>` lines rather than shell assignments. The
  first launcher incorrectly injected the whole API line and received HTTP 401.
  It did not reach inference or return usage. The exact 245 KB artifact is
  preserved as `phase-03a1-r4-attempt-01-auth-misconfigured.json` with SHA-256
  `633e4121e0adfd95e37ed678af4368f20331e6af6d2c2fca1542b8bf3b67726d`;
  no credential value is persisted.
- Correctly parsed Provider probes: medium and high each returned
  `gpt-5.6-terra-2026-07-09`, a response ID, 105 input and 27 output tokens, and
  960 usage-accounted microusd. `probe_ready=true`; total probe dispatches=2 and
  actual usage-accounted cost=1,920 microusd.
- Frozen matrix outcome: the first `untuned_fast_frontier_slow_medium` Slow call
  was dispatched, then returned HTTP 400 `BadRequestError`, Provider type
  `invalid_request_error`, parameter `response_format`, and no response ID or
  usage. R4 records `failed_provider_call`, `actual_cost_unknown`, and incomplete
  accounting. The global abort left Qwen+Terra high and both Terra-reference
  conditions at zero calls with `not_run_budget_rejected`.
- Canonical r4 SHA-256 is
  `e4735b496bfdad6f04c460be1c998b1f04732af946d99e95ad5d7299e2df8e34`.
  Offline artifact replay/tamper validation passed; r2/r3 hashes remain
  unchanged. `phase_completion_ready=false` is an honest matrix blocker, not a
  model-quality conclusion. No r5, prompt/schema repair, training, or Phase 03B
  work begins in this phase.
- Root final `make preflight`: passed with 138 runtime/contract/integration tests
  and 100 ML tests plus all format, lint, strict mypy, contract/type drift,
  Phase 01B/02/03A1 artifact replay, layout, both locks, frozen offline pnpm,
  script compilation, Docker Compose, and diff gates.
- Final independent Terra review: Approve with no Critical or Important
  finding. Terra independently reran the same complete `make preflight`,
  confirmed both artifact hashes, dispatch/cost/readiness reconciliation,
  immutable r2/r3, zero-call aborts, and closed phase status, and made no
  Provider/API call. Durable review:
  `harness/code_review/phase-03a1-hosted-rerun.md`.

### 2026-08-24 — Phase 03A1-R Structured Outputs remediation and completed matrix

- Human gate: the user explicitly approved changing the Slow response Schema
  to the official OpenAI-supported form, required 29qg-first execution with
  official OpenAI only as fallback, and requested the complete test/matrix run.
- Root cause: `CapabilityModelOutput` used a Pydantic discriminated union that
  emitted `oneOf` plus `discriminator`. Official OpenAI Terra rejected the exact
  original `SlowModelOutput` with HTTP 400 on `response_format`, then accepted
  the otherwise-identical Schema after that union was represented as `anyOf`.
  The earlier gpt-4o-mini diagnostic showed the same validator behavior; those
  diagnostic calls are not evaluation evidence or part of r4 accounting.
- Red/Green: the new Schema regression failed on the original `oneOf`, then
  passed after removing only `Field(discriminator="capability")`. Existing
  strict Literal/extra-field semantics remained covered. Historical r2/r3
  semantic replay now compares semantic Schema identity without requiring a
  current wire-Schema fingerprint to equal the immutable historical one; report
  self-fingerprints continue to protect recorded provenance.
- 29qg-first confirmation: the corrected full `SlowModelOutput` returned
  `gpt-5.6-terra-2026-07-09`, a response ID, `finish_reason=stop`, a parsed
  Pydantic result, and complete usage of 546 input plus 92 output tokens. No
  official OpenAI fallback was used after this successful 29qg confirmation.
- Preservation: the original valid r4 terminal-blocker artifact was moved
  intact to `phase-03a1-r4-attempt-02-unsupported-schema.json`, SHA-256
  `e4735b496bfdad6f04c460be1c998b1f04732af946d99e95ad5d7299e2df8e34`.
  R2/R3 remain byte-identical with SHA-256
  `dbfb88c72317046b587ca63142adf71cf0f9b27d4b8f6bcb56e071bf290506b3`
  and `c5ed4955bf598db2807a30aa1795fdf886f5b2cf6de2d27ec17541dc10bbcd72`.
- Canonical execution: both formal probes and all four frozen medium/high
  hosted conditions completed through 29qg. R4 records probe dispatches=2,
  matrix dispatches=146, total new external dispatches=148, complete accounting,
  and 3,114,128 usage-accounted microusd. Canonical r4 SHA-256 is
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`;
  report fingerprint is
  `af37054e3fd6b5fe956ea58b21ef8467fd2ad0b551956057bca54dd75b216bc2`.
- Matrix quality evidence: Qwen+Terra medium/high had 10/32 and 8/32 valid Slow
  semantics, 2 and 1 reference matches, and zero end-to-end-valid episodes.
  Terra-reference medium/high had 8/32 and 10/32 valid Slow semantics, with
  3 and 1 end-to-end-valid/reference-matching episodes. Every hosted condition
  recorded zero false completions and zero policy violations. These are failure
  slices for a later training decision, not a quality pass.
- Final root `make preflight`: passed with 138 runtime/contract/integration
  tests and 101 ML tests, plus runtime/ML Ruff, strict mypy, contract and
  TypeScript drift checks, Phase 01B/02/03A1-H/03A1-B/03A1-E/r4 replay and
  tamper gates, layout, both uv locks, frozen offline pnpm, script compilation,
  Docker Compose, and diff checks. Canonical r4 is valid and records
  `phase_completion_ready=true`.
- Review boundary: the earlier independent Terra approval covers only the
  preserved unsupported-Schema attempt. Post-remediation independent review,
  PR/CI/GitGuardian, commit, push, and merge have not run in this remediation.
  Phase 03B remains inactive pending a separate human decision.

### 2026-08-24 — Phase 03A1-V evaluation-validity smoke

- Human gate: the user asked to follow the proposed diagnostic next step and
  identify why the corrected hosted matrix still produced implausibly low
  success, while avoiding over-engineering.
- Scope: one frozen r2 fixture for each of accept, decline, clarification,
  replan, escalation, and disclosure refusal; 29qg `gpt-5.6-terra` medium plus
  the existing local Qwen Fast model. No retry, high-reasoning run, full
  matrix, official OpenAI fallback, training, or product work was dispatched.
- Red/Green: `ml/tests/test_validity_smoke.py` initially failed because the
  isolated diagnostic module did not exist. The minimum implementation added
  only public Provider-state parity, explicit dynamic-field semantics, and an
  explicit verifier-evidence requirement for Fast completion claims. Focused
  regression passed 35 tests.
- Result: the selected canonical-r4 baseline was 0/6 end-to-end valid, 2/6
  Slow semantic valid, 2/6 raw capability exact, and 1/6 Provider exact. The
  r5 smoke was 5/6 end-to-end valid, 6/6 Slow semantic valid, 5/6 raw
  capability exact, 5/6 Provider exact, and 6/6 Qwen Fast `not_done`, with
  zero policy violations.
- Remaining disagreement: the fee fixture's visible goal constrains recurring
  monthly price, but the Provider verifier and scripted oracle enforce separate
  twelve-month-total predicates that are not present in the model-visible goal
  or constraints. Terra's acceptance produced the sole invalid Provider
  outcome/false completion. This is evaluation-contract evidence, not an
  unambiguous model reasoning failure.
- Provider evidence: all six Terra calls returned auditable identities and
  usage through 29qg. Recorded conservative usage-accounted cost was 117,456
  microusd. R5 SHA-256 is
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`;
  report fingerprint is
  `e6a9072bd9790f6c801962a2f41c1274ab2179d5bb0fb19c3b5c9580497124fd`.
  Canonical r4 remained byte-identical at
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`.
- Final `make preflight`: passed with 138 runtime/contract/integration tests,
  105 ML tests, runtime/ML Ruff and strict mypy, contract/TypeScript drift,
  Phase 01B/02/03A1-H/03A1-B/03A1-E/r4/r5 artifact checks, layout, both uv
  locks, frozen offline pnpm, script compilation, Docker Compose, and diff
  checks.
- Terminal status: Phase 03A1-V is complete. No implementation phase is active;
  Phase 03B remains inactive pending a separate human decision.

### 2026-08-24 — Phase 03A1-R/V final independent closeout

- Terra final independent re-review decision: `Approve`, with no unresolved
  Critical or Important findings.
- Terra actually ran 47 Phase R/V, adapter, and schema focused tests, plus
  `make hosted-rerun-source-check`, `make hosted-rerun-check`, and
  `make validity-smoke-check`; all passed.
- Terra made no Provider/API call, generator/model call, or Git operation and
  did not read `.env`.
- Root independently ran the complete `make preflight`, which exited 0 with
  138 runtime tests passed and 115 ML tests passed. Root's gate also passed
  all format, lint, strict mypy, contract, TypeScript, artifact, layout, uv
  lock, offline pnpm, `compileall`, Docker Compose, and diff checks. This is
  root execution evidence, not a Terra observation.
- The remediated R5 checker typed-validates the embedded summary and
  recomputes or binds model-call count, hosted maximum cost, actual cost and
  accounting, failure slices, model/prompt provenance, and fixed disclosure
  text. Refingerprinted tamper tests cover headline metrics, selection,
  references, summary cost, model-call count, disclosure text, failure
  slices, model provenance, and nested R4 evidence.
- Canonical R4 SHA-256 remains
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`;
  canonical R5 SHA-256 remains
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`.
- This closeout does not assert PR, CI, GitGuardian, commit, push, or merge
  completion. Training, PostgreSQL, Temporal, real tools/Providers,
  deployment, and UI remain inactive.

### 2026-08-24 — Phase 04A implementation gates and independent re-review pending

- Luna's runtime-focused implementation report records 10 Phase 04A tests
  passed, API Ruff and mypy passed, and `make preflight` with Runtime 162 and
  ML 115 tests passed.
- Luna's policy-focused report records 86 relevant tests passed, mypy over 21
  files and Ruff passed, benchmark/hosted-rerun/validity-smoke checks passed,
  and `ml/uv.lock` byte-identical to `HEAD`.
- Sol's focused integration run records 24 combined tests passed.
- Sol's final `make preflight` records Runtime 162 and ML 115 tests passed,
  with contracts, artifacts, layout, locks, frozen offline pnpm, and Compose
  checks passed.
- Sol's `git diff --check` passed. The canonical r4 SHA-256 remains
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`; the
  canonical r5 SHA-256 remains
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`. No
  `ml/` or historical artifact diff was observed.
- Terra's first independent review returned Request Changes with two Critical,
  four Important, and one Minor finding. Remediation is reported complete;
  final independent re-review is still pending. No final Terra approval
  artifact is recorded here.
- Phase 04A remains the single active phase. These are implementation-gate
  results only; Phase 04A is not marked complete and no subsequent phase is
  activated. Training, further evaluation, PostgreSQL, Temporal, real tools
  or Providers, deployment, channels, voice, and UI remain inactive.

### 2026-08-24 — Phase 04A final independent review and closeout

- Terra's first independent review returned Request Changes with two Critical,
  four Important, and one Minor finding. The implementation remediation was
  completed before the second review.
- Terra's second independent read-only review returned **Approve**. The
  focused second-review run passed 67 tests and included an additional
  execution-claim CAS injection check at the Case version boundary.
- Terra confirmed the final repository evidence: `make preflight` passed with
  Runtime 162 and ML 115 tests; contracts, artifacts, layout, locks, frozen
  offline pnpm, and Compose checks passed.
- Canonical r4 SHA-256 remains
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`; the
  canonical r5 SHA-256 remains
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`. No
  `ml/` or historical Phase 03A1 artifact diff was observed.
- Durable review: `harness/code_review/phase-04a-thin-agent-runtime.md`.
- The review was read-only: no model/API call, credential read, Git
  publication, deployment, or external service action occurred.
- Phase 04A is complete and independently approved. No implementation phase
  is active after it; Phase 03B, training, PostgreSQL, Temporal, real tools or
  Providers, deployment, channels, voice, UI, and release remain inactive and
  require a new explicit gate.

### 2026-08-25 — Phase 04B activation and frozen preflight

- Human gate: the user explicitly approved Phase 04B Model-backed Thin Agent
  Runtime and required Sol-only architecture/integration, Luna xhigh
  implementation, and independent Terra high review.
- Refreshed base: local and remote `main` are synchronized at `75974da`, the
  Phase 04A squash merge from PR #12. The clean active branch is
  `feat/phase-04b-model-backed-runtime`.
- Preserved work: one old Phase 03A1 validity-smoke stash remains untouched.
  The separately pushed architecture-documentation branch at `2ed4a90` is not
  the Phase 04B base and has not been merged into this branch.
- Frozen seam: existing `FastAdapter`/`SlowAdapter` protocols and canonical
  contracts remain the Runtime interface. One runtime-owned OpenAI-compatible
  Structured Outputs path may be added; no provider registry, plugin system,
  generic gateway, or Runtime-to-ML dependency is allowed.
- Evaluation reuse decision: `ml/evaluation/openai_frontier.py` remains
  evaluation-only because it binds Phase 03A1 provider/model, budget, cost,
  attestation, replay, artifact, and ML-private compiler behavior. It will not
  be imported, moved, or copied wholesale into Runtime.
- Baseline `make preflight`: passed before Phase 04B deliverable edits with 162
  runtime/contract/integration tests and 115 ML tests, plus Runtime/ML Ruff,
  strict mypy, contract/TypeScript drift, Phase 01B/02/03A1 artifact checks,
  layout, both uv locks, frozen offline pnpm, script compilation, Docker
  Compose, and Git diff checks.
- External boundary: no model/API call was made, no credential or `.env` was
  read, and the optional manual real-model smoke remains unauthorized.
- Frozen exclusions: no Phase 03A1 continuation, r6/r7, training, PostgreSQL,
  Temporal, real tool/Provider, authentication, channel, voice, UI, deployment,
  release, credential, or PII work.

### 2026-08-25 — Phase 04B implementation, Sol remediation, and local gate

- Delegation: after Sol froze the adapter seam, acceptance criteria, file
  ownership, and verification plan, one Luna xhigh implementer owned all
  product code/tests. Luna was explicitly prohibited from touching Sol harness
  files, `ml/`, historical artifacts, `.env`, credentials, Git publication, or
  external model/API calls.
- Red evidence: the initial Phase 04B architecture check produced two failures
  and one pass because the runtime adapter package and executable server did
  not exist.
- Initial implementation: added one runtime-owned OpenAI-compatible Chat
  Completions Structured Outputs adapter, strict semantic DTOs and deterministic
  compilers, stable typed failure categories, explicit scripted/model
  configuration, a localhost server command, fake-transport integration tests,
  and a real TCP/HTTP scripted black-box flow.
- Sol initial integration findings: failed or stale Slow work could leave a
  half-created deterministic Case; stale Slow, explicit refusal, and SDK
  timeout/zero-retry construction required direct regression coverage; Runtime
  should use the repository's already validated OpenAI 2.51.0 behavior surface
  rather than a second 1.x path.
- Sol finding remediation: repository creation now occurs only after Slow
  success and coordinator acceptance; tests prove Slow transport/stale failures
  persist no Case or authority state and Fast stale failure creates no approval
  or Provider confirmation; refusal and production client settings are covered;
  Runtime pins `openai==2.51.0`.
- Sol pre-review verification: the Phase 04B focused suite passed 16 tests;
  affected Ruff and strict mypy passed; `git diff --check` passed. Sol's complete
  `make preflight` passed with Runtime 178 and ML 115 tests plus every
  repository-native format, lint, type, contract/type drift, artifact, layout,
  lock, offline pnpm, compile, Compose, and diff gate.
- Initial independent Terra review: Request Changes with no Critical and one
  Important finding. `nan`, `inf`, and `-inf` timeout values could bypass the
  positive check and enter model serving.
- Review remediation: process configuration and the adapter constructor now
  require a finite positive timeout. Six parameterized cases produced four
  failures and two passes against the old behavior and all pass after the fix.
- Final independent Terra rereview: Approve with no remaining Critical,
  Important, or Minor finding. Terra independently passed 32 focused Phase
  04B/04A tests and complete `make preflight` with Runtime 184 and ML 115 tests.
  Durable review: `harness/code_review/phase-04b-model-backed-runtime.md`.
- Sol post-remediation focused verification passed 22 tests. After the durable
  review evidence was complete, Sol's final `make preflight` passed with
  Runtime 184 and ML 115 tests plus every repository-native format, lint, type,
  contract/type drift, artifact, layout, lock, offline pnpm, compile, Compose,
  and diff gate.
- Scope audit: no `ml/`, `data/evaluation/`, `data/manifests/`, `.env`,
  credential, Phase 03A1 artifact, training, database, Temporal, real
  tool/Provider, authentication, channel, voice, UI, deployment, or release
  diff/action occurred. No external model/API request was made.
- Local status: Phase 04B implementation and independent review gates are
  approved. PR publication, CI phase-gate, GitGuardian, squash merge, merged
  branch cleanup, and final synchronized-main verification remain pending.

### 2026-08-25 — Phase 04B initial PR gate and Sol integration decision

- Publication: commit `bfe9915` was pushed on
  `feat/phase-04b-model-backed-runtime` and opened as bounded PR #13 against
  `main`.
- Hosted evidence on initial PR head: GitGuardian Security Checks passed in one
  second and the repository `phase-gate` passed in 1 minute 20 seconds.
- Sol reviewed the complete 29-file PR diff, clean synchronized branch, final
  local Runtime 184 / ML 115 preflight, scope audit, dependency and lock
  changes, durable Terra approval, and live hosted gate state. Final decision:
  Approve for squash merge after this evidence-only commit passes its CI and
  GitGuardian rerun.
- No external model/API call occurred, no credential or `.env` was read, and
  `ml/`, `data/evaluation/`, `data/manifests/`, and historical Phase 03A1
  artifacts remain unchanged. No next phase is active.

### 2026-08-25 — Phase 04B merge and synchronized-main closeout

- Evidence-only PR head `0f65238` passed GitGuardian Security Checks in eight
  seconds and the repository `phase-gate` in 1 minute 26 seconds.
- PR #13 was squash merged to `main` as `6daa1bc`. Sol fetched the merged head,
  confirmed the short-branch tree was identical to `origin/main`, and
  fast-forwarded local `main` without rewriting history.
- Post-merge `make preflight` on synchronized `main` passed with Runtime 184
  tests and ML 115 tests plus every repository-native format, lint, strict
  mypy, contract/type drift, Phase 01B/02/03A1 artifact, layout, lock, frozen
  offline pnpm, compile, Compose, and diff gate.
- The GitHub `Repository checks` push run for `main@6daa1bc` completed
  successfully. The local and remote
  `feat/phase-04b-model-backed-runtime` branches were safely deleted only after
  merge, clean-worktree, pushed-head, no-unique-work, and tree-equivalence
  checks. The pre-existing Phase 03A1 stash remained untouched.
- Phase 04B is complete. No implementation phase is active, and this closeout
  does not authorize Phase 03B, training, data expansion, a real-model smoke,
  PostgreSQL, Temporal, real tools/Providers, channels, voice, UI, deployment,
  or release.

### 2026-08-25 — Architecture documentation and Phase 03B experiment handoff

- Human scope: update the completed Phase 04B documentation, reconcile the
  previously discussed Agent architecture document, and prepare a compact
  Phase 03B fine-tuning handoff for a fresh session. This was docs-only and did
  not activate Phase 03B.
- The existing `docs/agent-architecture-alignment` branch was brought forward
  to `main@6daa1bc` without rebasing or rewriting its published history. The
  architecture now distinguishes implemented Runtime/ML surfaces from target
  services and records the concrete Phase 04B OpenAI-compatible adapter rather
  than claiming a generic model gateway exists.
- The proposed Phase 03B plan commits the experiment direction to a bounded
  Qwen3-4B QLoRA smoke and same-model untuned-versus-tuned comparison after
  readiness passes. It keeps human review, evaluation validity, held-out
  isolation, safety gates, power analysis, expansion, and model promotion as
  explicit sequential decisions.
- The first `make preflight` was not a pass: Runtime reached one failing
  Phase 03A0 documentation-contract test because the Phase 03B plan row no
  longer contained the required phrase `Decided from Phase 03A1 failure
  slices`. The phrase was restored without changing the test or phase meaning.
- The corrected complete `make preflight` passed with Runtime 184 tests and ML
  115 tests plus every repository-native format, lint, strict mypy,
  contract/type drift, Phase 01B/02/03A1 artifact, layout, lock, frozen offline
  pnpm, compile, Compose, and diff gate.
- No product code, test, contract, dataset, ML artifact, `.env`, credential,
  model, Provider, training, or external service was changed or invoked. No
  implementation phase is active.

### 2026-08-25 — Phase 03B Gate 0 readiness audit and Stage 0A packet

- Activation baseline: clean synchronized `main` and fetched remote main at
  `600c18b2f5e987d0727edab6d59549d1e8045215`; Phase 04B was complete, no other
  implementation phase was active, and the historical Phase 03A1 stash was
  not touched.
- Gate 0 audit verdict: `NEEDS_BOUNDED_REMEDIATION`. The Phase 02 review was
  still `pending_human`; 80/24 source records represented only 20/6 distinct
  scenarios; Phase 02 oracle labels included Slow-owned acceptance/completion;
  r5 was diagnostic rather than Arm A; fee-total-cost visibility, identical
  A/B Fast inputs, explicit decoding, and first-class safety classifiers were
  not yet frozen.
- Sol froze the portfolio-demo boundary: same cached attested MLX 4-bit base,
  train/dev only, six-scenario descriptive evaluation, adapter as the only A/B
  variable, no statistical-significance or sealed-test claim, and no generic
  training infrastructure. The active contract is
  `harness/build/phase-03b-qwen-qlora-smoke.md`.
- Stage 0A implementation generated a deterministic 16-record train/dev-only
  packet covering all 13 train/dev families plus three high-risk provider
  contrasts. It constructs only the 26 train/dev scenarios, keeps oracle and
  historical response variants reviewer-only, validates proposed targets as
  canonical proposal-only `FastModelOutput`, and leaves every human field
  pending.
- Sol rejected the first implementation's misleading `allowed_response_texts`
  and full-128 construction path. Luna separated historical variants from the
  proposed safe response set and filters split assignments before trajectory
  generation, so no test trajectory is constructed or selected.
- Sol focused verification passed 13 tests, affected Ruff and strict mypy, the
  Phase 03B packet drift check, and `git diff --check`. The first complete
  `make preflight` was not a pass: one historical Phase 03A0 contract test
  rejected a renamed Phase 03B outcome in `PLANS.md`. Sol restored the frozen
  outcome wording without changing the test.
- The corrected complete `make preflight` passed with Runtime 184 and ML 128
  tests plus format, lint, strict mypy, contracts/types, Phase 01B/02/03A1 and
  Phase 03B artifact checks, layout, both locks, frozen offline pnpm, script
  compile, Compose, and diff gates.
- Historical Phase 03A1 hashes remained unchanged: r2
  `dbfb88c72317046b587ca63142adf71cf0f9b27d4b8f6bcb56e071bf290506b3`,
  r3 `c5ed4955bf598db2807a30aa1795fdf886f5b2cf6de2d27ec17541dc10bbcd72`,
  r4 `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`,
  and r5 `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`.
- Independent Terra review approved Stage 0A with no Critical or Important
  finding. Sol declined one non-blocking redundant manifest-header check because
  repository preflight already verifies the historical Phase 02 artifact
  before the packet drift gate. Durable review:
  `harness/code_review/phase-03b-readiness-stage-0a.md`.
- No model was loaded or run; no training, download, external API, Provider,
  credential, `.env`, checkpoint, adapter, optimizer state, r6/r7, data
  expansion, or historical-artifact modification occurred. All 16 human
  decisions remain pending, so Gate 0 remains `NEEDS_BOUNDED_REMEDIATION` and
  Stage 0B is not active.

### 2026-08-25 — Phase 03B owner-directed independent source review

- The project owner explicitly directed a fresh-context subagent to perform the
  16-record source review and directed Sol to make the final decision instead
  of requiring the owner to label the packet personally.
- A clean-context Terra high reviewer read every complete public observation
  and reviewer-only source label. It accepted 16/16 with all seven required
  correctness/safety labels true and found no global action mapping that was
  too coarse for the reviewed records.
- The review is recorded only as `independent_agent_review`, never human review.
  The packet's human fields remain pending and Phase 02 remains
  `pending_human` / `training_ready=false`.
- Sol independently recomputed the public fee, disclosure, transfer,
  clarification, approval/evidence, completion, and Fast-authority conditions.
  The two fee traps exceeded the public 90000 annual target at 118200 and
  116400; only the two escalation records exposed transfer availability; all
  accept candidates remained confirm-plus-Slow-review proposals with null
  action intent and `not_done` completion.
- Sol accepted the independent review for this bounded portfolio smoke. Stage
  0A source qualification passes under the owner's explicit waiver. Gate 0
  remains `NEEDS_BOUNDED_REMEDIATION` because Stage 0B evaluator parity,
  identical A/B controls, explicit decoding, safety checks, and review are not
  yet complete. No model execution or training is authorized by this decision.
- Durable evidence:
  `harness/code_review/phase-03b-source-qualification-agent-review.md`.

### 2026-08-25 — Phase 03B Gate 1 pretraining remediation and PRETRAIN_BLOCK

- Clean-context Terra returned `PRETRAIN_BLOCK`, and Sol accepted the three
  bounded findings: unsupported numeric fact checks were not bound to each
  public `SafeObservation`; result evidence lacked fail-closed role, source,
  and content provenance; and Arm B could run without a canonical Arm A
  baseline and exact control/runtime/scenario parity checked before generation.
- The old Arm A evaluator diagnostic exposed real public-number gaps: `7200
  exceeds 7500` and `81,400 exceeds 90,000`. The remediation now checks only
  the nearest comparison numbers when both are present in the same public
  observation or its public target annual cap. It does not rewrite the old
  diagnostic result.
- The previously executed local-only token-fit command was:
  `env HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --project ml python -m scripts.prepare_phase03b_experiment --verify-token-fit --model-path <frozen-local-snapshot>`; its observed output included a warning followed by
  `phase03b token fit: verified`, with full-train tokens 752--850, eval-prompt
  tokens 688--775, 26 rows, and no truncation. The frozen snapshot path is
  intentionally not persisted in repository evidence.
- The Phase 03B runner now writes canonical role, an evaluation-pipeline
  fingerprint bound to the evaluator and runner sources, and recomputable
  content fingerprint. Arm B requires a canonical Arm A
  result and validates its schema, fingerprints, runtime identity, scenario
  order, and all non-adapter controls before any generation. This is a
  bounded remediation; training and real model execution remain blocked.
- Arm A remains an honest reference: its safety failures are reported and do
  not create a prior zero-failure requirement for starting Arm B. Arm B must
  have zero policy, PII/disclosure, stale-pin, authority, and unsupported-
  response violations, and its false-completion count must not exceed Arm A.
  Sol records this as a correction of the original hard-gate interpretation;
  requiring both arms to have zero safety failures would make an honestly
  failing baseline prevent the comparison by construction.
- Focused evidence for this remediation: Phase 03B evaluator and runner tests
  passed (`25 passed`), ML strict mypy passed for the changed source files,
  `make phase03b-experiment-check` reported `phase03b experiment artifacts:
  ok`, Ruff passed, and `git diff --check` passed. No model, training,
  download, external API, or credential was used; no generated real-model
  result JSON was changed.

### 2026-08-25 — Phase 03B third Terra PRETRAIN_BLOCK remediation

- A third clean-context Terra review returned `PRETRAIN_BLOCK`. Sol accepted
  the findings that the canonical Arm A validator did not return and persist
  its false-completion count/content fingerprint for the Arm B relative gate,
  and that an overwrite could alias the baseline result path. The review is
  independent Agent evidence, not human review.
- The runner now validates the nested non-negative Arm A
  `false_completion.count <= episodes`, records the canonical Arm A content
  fingerprint and A/B counts in B evidence, computes
  `false_completion_not_above_arm_a`, and exposes the final
  `arm_b_hard_gates_pass` from six absolute safety zero gates, the relative
  gate, and slow-call zero. Arm A remains a descriptive reference.
- The runner rejects equal resolved output/baseline paths before adapter
  generation, including with `--overwrite`; focused tests cover pipeline,
  content, runtime, shared-control, and scenario-order tamper cases before
  generation and verify the baseline bytes remain unchanged on the alias path.
- This is a bounded remediation only. The current verdict remains
  `NEEDS_BOUNDED_REMEDIATION`; training, real model execution, and any result
  JSON rerun remain blocked pending independent review and a fresh canonical
  Arm A baseline. No model, training, download, external API, credential,
  historical artifact, or real result JSON was accessed or changed.
- Focused verification passed: Phase 03B evaluator/runner tests (`37 passed`),
  `make format-check`, `make lint`, `make typecheck`,
  `make phase03b-experiment-check` (`phase03b experiment artifacts: ok`), and
  `git diff --check`.

### 2026-08-25 — Phase 03B fourth Terra Important remediation

- A fourth clean-context Terra review returned `PRETRAIN_BLOCK` with two
  Important findings, both accepted by Sol: canonical schema-valid evaluation
  treated a structured `not_done` claim as sufficient even when response text
  asserted completion, and baseline aggregate false-completion counts were not
  reconciled against all six episode metric booleans. This evidence is an
  independent Agent review, not human review.
- The evaluator now requires both structured completion claim/evidence safety
  and the assertive response-text detector for completion quality; an
  assertive response makes `completion_candidate_quality=false`,
  `false_completion=true`, and `end_to_end_valid=false` even with `not_done`.
- The baseline validator now requires aggregate episodes, actual episode list,
  and six entries to agree; every episode `metrics.false_completion` must be a
  real boolean, and the aggregate count must equal the recomputed episode sum.
  It returns only the verified recomputed count before B generation.
- Current verdict remains `NEEDS_BOUNDED_REMEDIATION`; training, real model
  execution, and result reruns remain blocked. No model, training, download,
  external API, credential, historical artifact, or real result JSON was
  accessed or changed.
- Focused verification passed: Phase 03B evaluator/runner tests (`40 passed`),
  `make format-check`, `make lint`, `make typecheck`,
  `make phase03b-experiment-check` (`phase03b experiment artifacts: ok`), and
  `git diff --check`.

### 2026-08-25 — Phase 03B fifth Terra Important remediation

- A fifth clean-context Terra review returned `PRETRAIN_BLOCK` with one
  Important finding, accepted by Sol: all reviewed Phase 03B targets require
  `fact_updates=[]`, but non-empty structured or raw fact updates were not
  classified as unsupported. This is independent Agent evidence, not human
  review.
- The Phase03B evaluator now marks any non-empty canonical `decision.fact_updates`
  unsupported and not grounded. The invalid/raw path applies the same narrow
  rule to present non-empty or malformed `fact_updates`; an explicit empty list
  remains non-violating. No historical Fast contract or generic fact-grounding
  system was changed.
- Current verdict remains `NEEDS_BOUNDED_REMEDIATION`; training, real model
  execution, and result reruns remain blocked. No model, training, download,
  external API, credential, historical artifact, or real result JSON was
  accessed or changed.
- Focused verification passed: Phase 03B evaluator/runner tests (`41 passed`),
  `make format-check`, `make lint`, `make typecheck`,
  `make phase03b-experiment-check` (`phase03b experiment artifacts: ok`), and
  `git diff --check`.

### 2026-08-25 — Phase 03B sixth Terra Important remediation

- A sixth clean-context Terra review returned `PRETRAIN_BLOCK` with two
  Important findings, accepted by Sol: duplicate JSON members could be silently
  accepted by the historical parser path, and output/baseline hard links were
  not rejected by the resolved-path alias check. This is independent Agent
  evidence, not human review.
- The Phase03B row path now recursively parses raw output with an
  `object_pairs_hook`; any duplicate member at any nesting level becomes
  `invalid_output` / `duplicate_json_key`, preserves bounded raw output, and
  forces `unsupported_response_violation=true`, `response_grounded=false`, and
  `end_to_end_valid=false`. Ordinary JSON remains unaffected.
- The runner now checks both resolved-path equality and `os.path.samefile` when
  both paths exist, before overwrite checks and generation. Samefile comparison
  errors fail closed; nonexistent output paths retain the normal B path.
- Current verdict remains `NEEDS_BOUNDED_REMEDIATION`; training, real model
  execution, and result reruns remain blocked. No model, training, download,
  external API, credential, historical artifact, or real result JSON was
  accessed or changed.
- Focused verification passed: Phase 03B evaluator/runner tests (`48 passed`),
  `make format-check`, `make lint`, `make typecheck`,
  `make phase03b-experiment-check` (`phase03b experiment artifacts: ok`), and
  `git diff --check`.

### 2026-08-25 — Phase 03B seventh Terra review and canonical-A-only approval

- Clean-context Terra returned `APPROVE_CANONICAL_A_RERUN` with no P0 or P1
  findings and one non-blocking P2 documentation finding. Sol accepted the
  recommendation and limited the next permitted action to one fresh
  canonical Arm A rerun.
- `docs/README.md` now points the active Phase 03B Gate 1 remediation to the
  executable harness contract and explicitly labels the planning document as
  the original non-authorizing proposal. Arm B, QLoRA training, data
  expansion, downloads, and external model calls remain blocked.
- No source, tests, result JSON, model, training, or historical artifact was
  changed or run in this documentation-only remediation.

### 2026-08-25 — Phase 03B canonical Arm A provenance STOP_AFTER_ARM_A

- Clean-context Terra returned `STOP_AFTER_ARM_A` with one Important finding:
  an injected adapter test path could be labeled `canonical` even though only
  a production local MLX run with successful historical checkpoint attestation
  may establish the canonical Arm A baseline. Sol accepted the finding.
- The bounded fix distinguishes `adapter is None` production construction from
  injected test adapters. Production local results use exact
  `result_role=canonical`, `execution.mode=local_mlx`, and
  `checkpoint_attestation=observed_local_files`; injected A/B results are
  forced to `result_role=diagnostic` with `execution.mode=injected_test`.
  Canonical Arm A baseline validation rejects diagnostic provenance before B
  generation. No production bypass or test-only canonical switch was added.
- Only a fresh production canonical Arm A rerun is allowed after this fix;
  Arm B, QLoRA training, and all model execution remain blocked pending Sol's
  next review decision. No real result JSON, model, training, download,
  external API, credential, or historical artifact was accessed or changed.

### 2026-08-25 — Phase 03B canonical Arm A and one-smoke authorization

- Sol reviewed the fresh canonical result
  `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned.json`:
  SHA256 `b2a994d1eea6989cadbcf9873d8c7bdc7722ed0b4764807fd1245c4a87d3b0f0`;
  content fingerprint
  `d6b2f5e040ed4f759cce628418a530782c54d45d44a007ab13fe48b967ad5be2`;
  evaluation-pipeline fingerprint
  `c3a7a3bf91a775aba226f06d15e5fda28530502c92bbb813aeb52198148e881b`.
- The result records canonical/local_mlx/observed_local_files execution over
  six episodes. Counts were schema/canonical `1`/`1`, end-to-end `0`,
  dialogue-act `0`, policy `6`, unsupported `3`, and false-completion, PII,
  disclosure, stale-pin, and authority all `0`. Wall time was `29250.704 ms`;
  latency total/median `28109`/`4515.5 ms`; input/output tokens `4461`/`1765`;
  MLX peak memory `3183546516` bytes; process RSS `2436792320` bytes.
- Raw hashes matched the pre-provenance run. The pre-provenance,
  pre-remediation, and detector-diagnostic files remain retained with hashes
  `636c1f...`, `bd7647...`, and `2a6929...` respectively.
- Complete `make preflight` exited 0: Runtime `184` tests passed, ML `177`
  tests passed, and the Phase 01B/02/03A1/03B artifacts, format, lint, mypy,
  contracts/types, layout, both `uv` locks, offline pnpm, compile, and Compose
  gates passed.
- Sol set the status to `READY_FOR_ONE_QLORA_SMOKE` and authorized exactly one
  frozen 40-iteration QLoRA smoke followed by canonical Arm B evaluation. Arm B
  has not been trained; no additional training, data expansion, or model
  matrix is authorized.

### 2026-08-25 — Phase 03B frozen QLoRA training and canonical-B authorization

- Sol's real training execution used the frozen native MLX-LM config against
  the local snapshot in offline mode, writing the adapter only to the ephemeral
  path `/private/tmp/proxyloop-phase03b-adapter.<ephemeral>`. The command exited
  0; no network fallback or external model API was used.
- The executed command, with the local snapshot path redacted, was:
  `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 uv run --project ml python -m mlx_lm lora -c data/experiments/phase-03b-qlora-smoke/qlora-smoke.yaml --model <frozen-local-snapshot> --train --data data/experiments/phase-03b-qlora-smoke --adapter-path /private/tmp/proxyloop-phase03b-adapter.<ephemeral>`.
- Sol observed trainable parameters `3.670M/4022.468M` (`0.091%`); validation
  loss `3.886` at iteration 1, `3.441` at 10, `2.744` at 20, `1.997` at 30,
  and `1.706` at 40; training loss `3.850` at 5, `3.602` at 10, `3.163` at
  15, `2.687` at 20, `2.087` at 25, `2.135` at 30, `1.699` at 35, and
  `1.574` at 40. Trained tokens were `2780`; peak memory `5.412 GB`; observed
  session wall time approximately `128.4 s` from accumulated tool waits.
- Final weights were `14692068` bytes with SHA256
  `801d2d96908dbb49df146d568b496f2d831c68ac128be14a33c50211cf76813c`.
  `adapter_config.json` was `1160` bytes with SHA256
  `070c605ed52337d57fcc676dc919d20d14507c47c8c4eb78622dd5d01a57e903`.
  The binary outputs remain ephemeral and are not committed as repository
  artifacts.
- Clean Terra returned `APPROVE_CANONICAL_ARM_B_EVAL`, accepted by Sol.
  Terra independently verified the frozen config, data, base identity, and
  hashes, but did not see the original training stdout. Loss and timing are
  therefore Sol execution evidence, not an independently reproduced quality
  result; loss decrease is not a task-quality conclusion.
- Status is training complete for the one frozen run. Exactly one canonical
  Arm B evaluation is authorized; no additional training, data expansion, or
  model matrix is authorized. No Arm B evaluation has yet been run.

### 2026-08-25 — Phase 03B final comparison and NO_GO_STOP_PHASE03B closeout

- Arm B result `data/experiments/phase-03b-qlora-smoke/results/arm-b-qlora.json`
  SHA256 is `274e71e06f708d70a66bc6c30a148cab283b27350f62d4862339d838d8036f36`;
  content fingerprint is
  `6a7e03a597ebafefb1748901a227b44784f1fe07b9869184f04a6340dcf1a634`;
  pipeline fingerprint is
  `c3a7a3bf91a775aba226f06d15e5fda28530502c92bbb813aeb52198148e881b`;
  provenance is canonical/local_mlx/observed_local_files; adapter fingerprint
  is `c3a4035d5735aa72687f2bd7507b3003a0622244856d5dc72dbefacb5a1f1651`.
- A/B controls matched except adapter identity. A recorded schema/canonical
  `1/1`, E2E `0`, dialogue `0`, policy `6`, unsupported `3`, false completion
  `0`, and PII/disclosure/stale/authority `0`; input/output `4461/1765`,
  latency total/median `28109/4515.5 ms`, MLX/RSS
  `3183546516/2436792320 bytes`, wall `29250.704 ms`. B recorded
  schema/canonical `0/0`, E2E `0`, dialogue `0`, policy counter `0` but
  `unassessable_due_to_6_of_6_invalid_json`, unsupported `4`, false completion
  `0`, and detected PII/disclosure/stale/authority `0` with most safety checks
  unavailable; input/output `4461/1442`, latency total/median `27613/4908 ms`,
  MLX/RSS `3700787440/2655387648 bytes`, wall `28726.628 ms`.
- All six B episodes failed `invalid_json`; unsupported `4/6` is not a complete
  enumeration. The Arm B hard gate is false. The six-scenario/three-family
  descriptive comparison and uncertainty boundary are in
  `data/experiments/phase-03b-qlora-smoke/results/comparison.md`.
- Final clean Terra returned `NO_GO_STOP_PHASE03B`, accepted by Sol. Important
  #1 stale documentation is fixed by this closeout. Important #2 policy zero
  is explicitly not treated as safety under six-of-six invalid JSON. Important
  #3 hard-gate failure is retained. A known P2 fenced-JSON duplicate-key
  limitation is recorded; no post-hoc source/evaluator change was made because
  it would not change No-Go and would contaminate the frozen conclusion.
- Final state is closeout-only. No data expansion, additional training, model
  rerun, promotion, deployment, or next phase is authorized. CI and merge have
  not occurred; this is not a merged or complete-phase claim. Clean Terra is
  independent Agent evidence, not human review.

### 2026-08-25 — Phase 03B final local validation

- Focused Phase 03B tests passed:
  `uv run --project ml pytest -c ml/pyproject.toml ml/tests/test_phase03b_readiness.py ml/tests/test_phase03b_experiment.py ml/tests/test_phase03b_smoke_runner.py -q` — `62 passed`.
- The first final `make preflight` stopped at the existing
  `test_phase_03a0_requires_eval_first_before_later_data_expansion` contract
  test because the PLANS Phase 03B status had lost the exact historical source
  phrase. Runtime had `183 passed, 1 failed`. Tests were not changed; PLANS was
  minimally restored with `Decided from Phase 03A1 failure slices`.
- The restored-state single contract test passed (`1 passed`). A complete
  `make preflight` then exited 0 with Runtime `184 passed`, ML `177 passed`,
  and format, lint, mypy, contracts/types, Phase 01B/02/03A1/03B artifacts,
  layout, both locks, offline pnpm, compile, and Compose all passing.
- `git diff --check` passed. Sol then ran
  `git diff --exit-code main -- ml/evaluation/src/proxyloop_evaluation/qwen_mlx.py ml/tests/test_qwen_mlx_adapter.py data/evaluation`; it exited 0 with no output, confirming no historical Phase 03A1 drift in those paths.

### 2026-08-25 — Phase 03B final clean review P1 documentation remediation

- Final clean Terra raised a P1 boundary finding: `arm_b_hard_gates_pass` is
  only a necessary detector-based safety summary. It is not sufficient for
  experiment Go, evaluability, task quality, or promotion; any future Go must
  independently satisfy schema, evaluability, and task-quality criteria.
- Terra reproduced the field boundary with an injected `{}` output: schema and
  end-to-end counts can both be `0` while `arm_b_hard_gates_pass=true` when the
  detector counters are zero. This confirms that the boolean cannot substitute
  for output evaluability or task-quality evidence.
- The final No-Go is therefore not only the boolean failure. It combines Arm B
  schema/canonical/E2E `0/6`, `invalid_json` in all six episodes, mostly
  unassessable apparent safety zeros, and unsupported `4/6`, which is not a
  complete enumeration.
- Sol accepted a documentation-only remediation. The frozen evaluator,
  pipeline fingerprint, A/B result JSON, and model evidence are unchanged and
  were not rerun: a post-hoc code/evaluator change would contaminate the frozen
  conclusion and over-engineer this portfolio demo.
- Final status remains `NO_GO_STOP_PHASE03B`, Phase 02 remains
  `pending_human`, and Phase 03B remains closeout-only with no merge or CI
  completion claim.

### 2026-08-25 — Phase 03B final evidence cleanup

- Sol first verified the exact ephemeral directory
  `/private/tmp/proxyloop-phase03b-adapter.3QTgt0`: it contained only
  `adapters.safetensors`, `0000040_adapters.safetensors`, and
  `adapter_config.json`; sizes and hashes matched the durable training
  evidence.
- Sol then permanently deleted that exact ephemeral directory, and
  `test ! -e /private/tmp/proxyloop-phase03b-adapter.3QTgt0` passed. The
  repository never staged the adapter weights.

### 2026-08-25 — Phase 03B post-review final local preflight

- After clean Terra `APPROVE_CLOSEOUT` and ephemeral adapter cleanup, Sol ran
  the complete `make preflight`; it exited 0 with Runtime `184 passed`, ML
  `177 passed`, and format, lint, mypy, contracts/types, Phase 01B/02/03A1/03B
  artifact checks, layout, both `uv` locks, offline pnpm, compile, and Compose
  all passing.
- The same final local validation recorded `git diff --cached --check` and
  `git diff --check` passing. This is local evidence only; it does not claim
  CI, GitGuardian, merge, or publication.

### 2026-08-25 — Phase 03B CI portability remediation evidence

- PR #15 first head `1e14c89` had GitGuardian passing, but its phase-gate
  failed at ML strict mypy on Linux because optional `mlx.core` and
  `transformers` were unavailable.
- The accepted remediation was limited to precise `import-not-found`/unused-
  ignore annotations on those two function-local imports. No dependency, lock,
  behavior, result, or test change was made.
- After the fix, local `make preflight` exited 0 with Runtime `184`, ML `177`,
  and all repository format, lint, mypy, contracts/types, artifact, layout,
  lock, offline pnpm, compile, and Compose gates passing. Clean Terra
  independently returned `APPROVE_FIX`; focused strict mypy over the two files
  passed, and `git diff --check` passed.
- CI rerun and push have not occurred; this entry makes no CI/GitGuardian/merge
  claim beyond the recorded first-head GitGuardian result.

### 2026-08-25 — Phase 03B post-merge synchronized-main closeout

- PR #15 (`https://github.com/SimondXu/ProxyLoop/pull/15`) first failed its
  phase-gate at head `1e14c89` on Linux optional-import mypy; the precise
  two-import annotation remediation was applied without dependency, lock,
  behavior, result, or test changes.
- Final PR #15 head `8557fd36a2d68b0a996a3ff4b0132671abd67573` passed the final
  phase-gate in `2m3s`; GitGuardian passed. It was squash merged at
  `2026-08-25T11:39:15Z` as `f441335441ce7380131cbcd448088320c3c50e95`.
- `main`, `origin/main`, and `HEAD` all resolve to the exact squash commit;
  the worktree is clean. The local experiment branch was deleted by the merge
  flow, and `git fetch --prune origin` confirmed the remote experiment branch
  deletion and pruned tracking ref. The existing stash remains untouched.
- Phase 03B is complete with final decision `NO_GO_STOP_PHASE03B`. No
  additional training, data expansion, model rerun, promotion, deployment, or
  next phase is authorized; no implementation phase is active.

### 2026-08-25 — Phase 03B docs closeout branch evidence

- From `f441335441ce7380131cbcd448088320c3c50e95`, the docs closeout branch
  `docs/phase-03b-closeout` changed only the eight current-state/evidence docs:
  `AGENTS.md`, `PLANS.md`, `README.md`, `docs/README.md`, the Phase 03B
  contract, the Phase 03B readiness preflight, `comparison.md`, and this
  build log.
- Full local `make preflight` exited 0 with Runtime `184`, ML `177`, and all
  repository gates passing. `git diff --check` passed. Clean Terra returned
  `APPROVE_DOC_CLOSEOUT` with no blocking findings.
- No model execution or training was run. No docs PR, CI run, or merge has
  occurred for this closeout branch.

### 2026-08-25 — Codex token-routing harness update

- Human gate: the user requested implementing the previously discussed harness
  changes to preserve Sol's strongest decision-making while reducing repeated
  context and subagent token use. No product or implementation phase was
  activated.
- Root context routing now distinguishes first orientation/material drift from
  delegated slices, replaces full historical build-log rereads with status,
  current-change, and newest-relevant evidence reads, and keeps architecture,
  authorization, canonical semantics, conflicts, and final gates with Sol.
- Explorer routing now defaults to fresh bounded context, minimal task packets,
  agent reuse for clarification, and a compact evidence card with explicit
  escalation triggers. The reusable prompt template exposes the same contract.
- Unchanged execution capacity: root remains Sol high, independent review
  remains Terra high, Luna implementer/explorer/fast-worker settings remain
  unchanged, and the concurrency cap remains three. No model or reasoning
  setting was downgraded.
- `make check-layout`, `python3 -m compileall -q scripts`, and
  `git diff --check` passed in the focused gate. Layout validation now fails
  closed if the routing sections or explorer evidence-card contract drift.
- Complete `make preflight` exited 0 with Runtime `184 passed`, ML `177 passed`,
  and all repository format, lint, strict mypy, contract/type drift, Phase
  01B/02/03A1/03B artifact, layout, lock, offline pnpm, compile, Compose, and
  diff gates passing.
- No subagent, external model/API call, credential, product code, training,
  deployment, commit, push, PR, CI, or merge was used or performed.

### 2026-08-25 — Minimal local Web demo implementation evidence

- Scope: `feat/minimal-local-web-demo` from `main@d2cda56`; changed only the
  owned Web, docs, phase-contract/context, status, and lockfile surfaces. The
  root untracked planning files remain untouched. No backend, contracts, ML,
  credentials, `.env`, external model, old-worktree branch, commit, push, PR,
  or merge action occurred.
- Red evidence before implementation: `pnpm --filter @proxyloop/web lint`
  returned `No projects matched the filters` because `apps/web` contained only
  `.gitkeep`.
- `pnpm install --lockfile-only --ignore-scripts --offline` passed and updated
  the workspace lockfile without downloading. A full offline install was not
  possible because the local pnpm store lacked
  `json-schema-to-typescript-15.0.4.tgz` and `@next/env-16.2.9.tgz`; no network
  fallback was attempted.
- Focused Web checks passed using the existing dependency tree from the old
  worktree as a read-only verification aid (temporary symlink removed before
  handoff): ESLint 9.39.3, TypeScript `tsc --noEmit -p apps/web/tsconfig.json`,
  and Vitest `2 files / 8 tests passed`. The old worktree was not edited.
- `git diff --check` passed. `make preflight` first hit the missing local root
  Node binaries, then passed after temporarily exposing the existing local
  dependency tree read-only: Runtime `184 passed`, ML `177 passed`, contracts,
  artifacts, layout, locks, compile, Compose, and diff gates all passed.
- `pnpm --filter @proxyloop/web lint/typecheck/test/build` were not run to a
  native exit because the current workspace install is unavailable offline;
  the direct focused equivalents above passed. Next production build was
  attempted with the temporary dependency symlink and failed closed because
  Turbopack rejects a `node_modules` symlink outside its filesystem root.
  Browser smoke and live Runtime/Web process checks remain unrun.

- After the final blank-conversation correction (the first consumer message now
  creates the Runtime Case instead of creating one on mount), the focused Web
  checks were rerun with the same read-only dependency-tree aid: ESLint and
  TypeScript exited 0; Vitest reported `2 files / 8 tests passed`. The
  workspace remains free of generated `node_modules` symlinks.

- Correction after the intent-gate remediation: the intermediate note above
  saying native Web scripts were unavailable is superseded for this local
  verification environment; it remains as historical evidence. The three
  native commands `pnpm --filter @proxyloop/web lint`,
  `pnpm --filter @proxyloop/web typecheck`, and
  `pnpm --filter @proxyloop/web test` all exited 0. Vitest reported `2 files /
  9 tests passed`, including the unsupported-initial-intent test.
- The explicit Webpack build command
  `pnpm --filter @proxyloop/web exec next build --webpack` exited 0. Next
  compiled successfully and prerendered `/` and `/_not-found` as static
  routes. This correction records only local native Web evidence; it does not
  claim a browser smoke, `make preflight` rerun, independent review, or CI.

- Sol's final native Web verification then recorded
  `pnpm --filter @proxyloop/web lint` exited 0,
  `pnpm --filter @proxyloop/web test` exited 0 with `2 files / 9 tests`, and
  `pnpm --filter @proxyloop/web build` exited 0; the `build` script is
  `next build --webpack` and generated static `/` and `/_not-found` routes.
  Sol initially ran build and typecheck in parallel; typecheck transiently
  failed with `TS6053` while the build replaced `.next/types`. A sequential
  typecheck rerun after the build exited 0. This is a validation-order race,
  not a source failure.
- Sol's final `make preflight` exited 0: Runtime `184`, ML `177`, and the
  format/lint/mypy/contracts/artifacts/layout/uv-lock/offline-frozen-pnpm/
  compile/Compose/diff gates passed.
- In-app Browser smoke used Runtime `127.0.0.1:8000` and Web
  `127.0.0.1:3012`. Unsupported vacation input stayed local; supported
  `Lower my mobile bill` showed Runtime-derived `$92` current, `$75` target,
  hotspot, and no device-financing change; one confirmation event produced a
  `$72` fictional offer with pending exact approval; an arbitrary pending
  correction stayed local and approval remained pending; exact approval
  produced a Verified receipt only with one matching completion Evidence and
  `execution_count` 1. Browser console warning/error output was empty. At
  `375x812`, document `scrollWidth` was `375` with no horizontal overflow.
  Servers, tab, viewport, and temporary dependency symlinks were cleaned up.
  No screenshot artifact was committed; independent review, CI, and merge
  remain pending.

### 2026-08-25 — Terra review remediation evidence

- Terra's independent review returned `REQUEST_CHANGES` with four P1 findings:
  missing repository Web gate, malformed Task Brief/approval fail-closed
  validation, an over-broad initial intent gate, and stale async responses
  after restart. Sol accepted all four findings. The durable review record is
  `harness/code_review/phase-minimal-local-web-demo.md`; rereview remains
  pending.
- Remediation stayed within Web, Makefile, docs, phase evidence, and review
  ownership. It added `make web-check` in the required order and connected it
  to `validate`; added explicit Money/Task Brief/pending Approval predicates;
  split intent matching into telecom + billing context + reduction outcome;
  and bound create/event/approval awaits to a monotonic session id with restart
  invalidation. Tests now cover malformed Task Brief/offer, negative and
  positive intent examples, and create/approval restart races.
- `make web-check` exited 0 sequentially: Web lint, typecheck, Vitest `2 files
  / 17 tests passed`, and `next build --webpack` generated static `/` and
  `/_not-found`. `git diff --check` exited 0.
- Final `make preflight` exited 0 with Runtime `184`, ML `177`, and format,
  lint, mypy, contracts, artifacts, layout, uv locks, frozen offline pnpm,
  compile, Compose, diff, and the Web gate passing. An earlier ordinary
  sandbox attempt was blocked by uv-cache permissions; an intermediate run
  without the temporary dependency aid failed at the existing root
  `tsc/json2ts` lookup after Runtime `182` and two contract-test failures. The
  final run used the existing dependency tree read-only and passed.
- No browser smoke was rerun for this remediation. No rereview approval, CI,
  commit, push, PR, or merge is claimed; final recommendation remains pending.

### Evidence clarification — intermediate preflight failure

- The intermediate command was one escalated `make preflight` invocation run
  without the temporary root dependency symlink. Its Runtime pytest phase
  completed with `182 passed, 2 failed`.
- The two failed tests were
  `test_generated_types_accept_exact_representative_fixture`, whose subprocess
  `pnpm exec tsc --noEmit -p contracts/typescript/tsconfig.json` reported
  `Command "tsc" not found`, and `test_generated_artifacts_have_no_drift`,
  whose `scripts/generate_contracts.py --check` subprocess `pnpm exec json2ts`
  reported `Command "json2ts" not found`.
- Because `unit-test` returned nonzero, Make stopped at that phase and did not
  continue to a later standalone `contracts-check` invocation. Thus the prior
  shorthand “root tsc/json2ts lookup after Runtime 182 and two contract-test
  failures” describes the causes inside those two failed pytest cases, not a
  second later command. The final preflight used the read-only dependency aid
  and passed; the failures remain recorded as historical evidence.

### 2026-08-25 — Final Evidence-ID/Task-Brief remediation and Terra approval

- The final source remediation rejected empty and whitespace-only `evidence_id`
  values in both Runtime payload parsing and completion receipt verification.
  Event responses now require both a valid Task Brief and a valid pending
  offer/approval before entering the Approval state. Added regressions cover
  both ID forms and a response with valid offer/approval but a missing Task
  Brief; it remains blocked without an approval action.
- Sol's final source verification passed Web lint/typecheck and Vitest `2 files
  / 20 tests`. Complete `make preflight` passed with Runtime `184`, ML `177`,
  the Webpack build, and all repository gates.
- The earlier full journey, in-app Browser, and mobile smoke passed. Browser
  smoke was not rerun after this final remediation. CI, commit, PR, merge, and
  phase closeout have not occurred.
- Terra's final rereview found no P0, P1, or P2 findings across six cumulative
  remediations and returned `APPROVE_PHASE_GATE`. This is an independent review
  recommendation, not a merge or phase-closeout claim.

### 2026-08-25 — PR #18 integration gate and Sol decision

- PR #18 (`https://github.com/SimondXu/ProxyLoop/pull/18`) passed the fresh-
  install phase gate in `2m29s`; GitGuardian Security Checks passed; head commit
  was `9aa8869`.
- Sol reviewed the PR file scope, local final preflight, Terra's
  `APPROVE_PHASE_GATE`, browser evidence, and PR checks. The integration
  decision is `APPROVE_FOR_SQUASH_MERGE`.
- Merge and branch cleanup have not occurred. No merged, cleaned, or phase-
  closed state is claimed.

### 2026-08-25 — PR #18 post-merge docs closeout

- Live local and GitHub evidence confirmed PR #18 was squash merged as
  `ef2ce536aab162f364b78939a08b993342c5af47`.
- The post-merge `main@ef2ce53` Repository checks passed in the recorded
  `2m27s`.
- The fully merged `feat/minimal-local-web-demo` branch was safely removed
  locally and remotely.
- The legacy UI worktree remains local-only at
  `/private/tmp/proxyloop-ui-worktree` on `feat/pine-inspired-ui-prototype` at
  `b8d7ee5`, with its three untracked planning scratch files preserved.
- `git diff --check` and `make check-layout` passed on the docs-only diff.
- The first ordinary `make preflight` attempt reproduced the recorded local
  dependency limitation: Runtime reported `182 passed, 2 failed` because root
  `pnpm exec tsc` and `pnpm exec json2ts` could not find their binaries. A
  read-only dependency-PATH retry was then blocked by the sandbox at the uv
  cache boundary. A later escalated root-bin PATH run passed Runtime `184`, ML
  `177`, contracts, artifacts, and layout before Web lint stopped because the
  current worktree had no package-level `node_modules` resolution.
- The final `make preflight` reused the preserved dependency tree through two
  temporary, current-worktree-only symlinks. It exited 0 with Runtime `184`, ML
  `177`, Web lint/typecheck, Vitest `2 files / 20 tests`, Webpack production
  build, contracts/artifacts/layout, lock, compile, Compose, and diff gates
  passing. Both temporary symlinks were verified and removed afterward; the
  legacy worktree remained unchanged.
- This closeout changes current-state and evidence documentation only. It does
  not rerun Browser checks or activate product, evaluation, training,
  persistence, Provider, channel, voice, deployment, or release work.
- No implementation phase is active after this closeout.

### 2026-08-25 — Local Conversation Intake UX activation and Gate 0

- User gate: after the independent PR #18 docs closeout, activate one bounded
  localhost fictional-telecom intake extension while retaining all deferred
  capabilities on the long-term roadmap.
- The branch `feat/local-conversation-intake-ux` was created from synchronized
  `main@0d0acb3`. This is the only active implementation phase; its executable
  contract is `harness/build/phase-local-conversation-intake-ux.md`.
- Read-only Gate 0 mapped the empty `POST /cases` boundary, fixed deterministic
  Case fixture, canonical Money/goal/bill/constraint fields, immutable event
  path, fixed `$72` fictional offer, exact approval/Evidence/completion checks,
  and current Web state/client/tests. An independent bounded explorer's lineage
  evidence was reconciled against the primary source by Sol.
- Gate decision: `GO_NARROW_SEAM`. One strict API-local four-field request can
  rebuild and validate the existing canonical Case without changing public
  contracts, Provider, authorization, approval, Evidence, execution, or
  completion semantics. Fixed fixture IDs remain an explicit Runtime-restart
  boundary for post-create correction.
- Focused pre-implementation baseline passed:
  `tests/integration/test_phase_04a_agent_runtime.py` and
  `tests/integration/test_phase_04b_model_runtime.py` reported
  `29 passed in 1.80s`.
- Product implementation, Browser smoke, independent review, full preflight,
  commit, push, PR, CI, merge, and cleanup have not occurred yet.

### 2026-08-25 — Local Conversation Intake UX implementation and Sol verification

- One Luna xhigh implementer completed the frozen API/Runtime/Web/test/UI-doc
  slice. Sol read every changed source file and the complete diff. No package,
  lockfile, canonical schema, Provider, persistence/identity, auth, model,
  channel, deployment, or infrastructure surface changed.
- Exact focused Runtime command excluding only the localhost black-box test:
  `UV_CACHE_DIR=/tmp/proxyloop-intake-uv-cache uv run --project runtime pytest
  -q tests/integration/test_phase_04a_agent_runtime.py
  tests/integration/test_phase_04b_model_runtime.py -k
  'not localhost_server_black_box'` reported `45 passed, 1 deselected`.
  Exact collection reported `45/46 tests collected (1 deselected)`.
- Final Web lint and typecheck exited 0. Vitest reported
  `2 files / 27 tests passed`. Next 16.2.9 Webpack production build compiled,
  typechecked, and generated static `/` and `/_not-found` routes.
- The first ordinary-sandbox `make preflight` attempt reached Runtime
  `200 passed, 1 failed`; the sole failure was the existing localhost
  black-box test's `PermissionError` while binding `127.0.0.1`. It stopped at
  `unit-test` and is recorded as an environment failure, not a passing gate.
- Final post-remediation `UV_CACHE_DIR=/tmp/proxyloop-intake-uv-cache make
  preflight` outside the socket restriction exited 0: Runtime `201`, ML `177`,
  Web `27`, and all Ruff, mypy, contracts, generated TypeScript, artifact,
  layout, uv-lock, frozen offline pnpm, compile, Compose, build, and diff gates
  passed.

### 2026-08-25 — Local Conversation Intake UX Browser and review evidence

- Real localhost Browser smoke verified unsupported input stayed local; the
  four facts filled a visibly local Draft Task Brief; create remained disabled
  before explicit confirmation and during editing; `$74` was rejected against
  a `$75` target; corrected `$100` was sent and returned as a verified Runtime
  Task Brief; post-create correction named the Runtime-restart/New-task
  boundary; exact approval of the `$72` fictional offer produced a Verified
  receipt with one matching Evidence ID and execution count `1`.
- A temporary non-production HTTP stub returned a structurally valid root
  `$92` / snapshot `$93` mismatch. The UI blocked with zero verified Task Brief
  or Approval actions. After review remediation, a final real-Runtime run kept
  the contradictory sentence `no change, but I want to change device
  financing` local with create disabled; explicit `yes` then completed the
  verified `$92 -> $72` journey.
- Desktop and `375x812` Draft/receipt checks had document/body
  `scrollWidth=375` and zero overflowing visible elements. Browser console
  warning/error output was empty.
- Tabs, viewport, Runtime/Web servers, the temporary fault stub, and both
  current-worktree dependency symlinks were cleaned. Generated
  `next-env.d.ts` dev-path noise was restored. The legacy UI worktree remains
  at `b8d7ee5` with exactly its original three untracked planning files.
- Initial independent Terra review returned `REQUEST_CHANGES`: one substantive
  P1 contradictory-language bug, one P1 evidence-record/count concern, one P2
  missing event stale-response test, and one P2 inaccurate Retry doc. Sol
  accepted and remediated the parser, durable evidence, event test, and docs.
  Exact runner/collector output resolved the static count concern. Final Terra
  rereview, commit, push, PR, CI, merge, and branch cleanup remain pending.

### 2026-08-25 — Final financing-parser remediation and second rereview gate

- Terra's first rereview confirmed the evidence, event stale-response, and
  Retry-documentation findings resolved, but returned `REQUEST_CHANGES` for one
  remaining P1: the negative-synonym check could miss `modify` in a sentence
  prefixed by `no change`.
- The same implementer replaced financing free-text positive detection with a
  normalized whole-answer allowlist. Both the original contradictory `change`
  sentence and Terra's exact `no change, but please modify device financing`
  sentence now stay local with create disabled; positive `yes` and `no change`
  remain covered.
- Final Web lint/typecheck/build exited 0 and Vitest reported
  `2 files / 28 tests passed`. Final full preflight exited 0 with Runtime
  `201`, ML `177`, Web `28`, and all repository gates passing.
- Final in-app Browser verification of Terra's exact `modify` sentence showed
  create disabled, zero verified Task Briefs, the local fixed-constraint alert,
  and no console warnings/errors. The temporary Web process, tab, dependency
  symlinks, and generated `next-env.d.ts` dev-path noise were cleaned.
- Second rereview by the same Terra reviewer, commit, push, PR, CI, merge, and
  branch cleanup remain pending.

### 2026-08-25 — Final hotspot-parser remediation and rereview gate

- Terra's second rereview confirmed all prior findings resolved but returned
  `REQUEST_CHANGES` for one analogous P1: free-text hotspot confirmation could
  accept `yes, remove mobile hotspot`.
- The same implementer moved both fixed boolean confirmations to normalized
  whole-answer allowlists and added the exact hotspot sentence as a fail-closed
  regression. Create remains disabled and no Runtime call is made.
- Final Web lint/typecheck/build exited 0 and Vitest reported
  `2 files / 29 tests passed`. Final full `make preflight` exited 0 with Runtime
  `201`, ML `177`, Web `29`, and all repository gates passing.
- Final in-app Browser verification of the exact hotspot sentence left the
  hotspot fact missing, create disabled, only the local fixed-constraint alert
  visible, no verified Task Brief present, and no console warnings/errors.
- The temporary Web process, isolated Browser tab, dependency symlinks, and
  generated `next-env.d.ts` dev-path noise were cleaned. Final same-Terra
  rereview, commit, push, PR, CI, merge, and branch cleanup remain pending.

### 2026-08-25 — Local Conversation Intake UX independent approval

- The same Terra reviewer inspected the current complete diff after hotspot
  remediation, found no P0/P1/P2 findings, and returned
  `APPROVE_PHASE_GATE`.
- The reviewer confirmed both fixed booleans use normalized whole-answer
  allowlists and retained the previously reviewed API/Case/drift/approval/
  Evidence/completion/stale-response conclusions. The reviewer did not rerun
  commands or Browser in this final pass.
- Sol's final local gate remains Runtime `201`, ML `177`, Web `29`, complete
  `make preflight`, and exact in-app Browser fail-closed evidence. Commit,
  PR-head CI/GitGuardian, merge, cleanup, and post-merge checks remain pending.

### 2026-08-25 — Local Conversation Intake UX PR #20 initial integration gate

- The 19-file bounded implementation/evidence commit `d432975` was pushed on
  `feat/local-conversation-intake-ux`, and PR #20 was opened against `main`.
  Root planning scratch remained untracked and excluded.
- PR #20 head `d432975` passed GitGuardian Security Checks in `1s` and the
  Repository `phase-gate` in `2m16s` through Actions run `32883127501`.
- Sol reviewed the complete source, complete staged diff, exact file scope,
  final local checks and Browser evidence, Terra's `APPROVE_PHASE_GATE`, and
  the initial PR checks. The decision is `APPROVE_FOR_SQUASH_MERGE` after this
  evidence-only commit passes its own fresh PR-head checks.
- Merge, source/squash tree verification, branch cleanup, post-merge `main`
  CI, and phase closeout remain pending.

### 2026-08-25 — Local Conversation Intake UX PR #20 post-merge closeout

- PR #20 final evidence head `b3e13ef` passed GitGuardian Security Checks and
  the fresh Repository `phase-gate` through Actions run `32883504165`.
- Sol approved squash merge. GitHub records PR #20 merged at
  `2026-08-25T18:26:42Z` as
  `02466df4e77801bb51a9c1da6cbdb0e29465d0a6`; the source and squash trees were
  identical.
- Post-merge Repository checks run `32883786070` completed successfully on
  exact `main@02466df`. Local `main` was synchronized with `origin/main`.
- The fully merged `feat/local-conversation-intake-ux` branch was removed
  locally and remotely after confirming no unique unpushed work would be lost.
  The legacy UI worktree remained local-only at `b8d7ee5` with exactly its
  three original untracked planning files.
- This closeout changes only current-state and evidence documentation. It does
  not activate Phase 04, PostgreSQL, Temporal, model training or promotion,
  real tools or Providers, authentication, channels, voice, production UI,
  deployment, or release. No implementation phase is active.
- On `docs/pr20-post-merge-closeout`, `git diff --check`, `make check-layout`,
  and the complete `make preflight` passed before publication. The full gate
  included Runtime `201 passed`, ML `177 passed`, Web `29 passed`, Web
  lint/typecheck/build, contract and experiment artifact checks, lock checks,
  offline pnpm lockfile verification, Python compilation, and Compose config.
