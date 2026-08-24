# ProxyLoop Agent Instructions

This file is the repository-level operating contract for Codex and delegated agents. Product requirements remain authoritative in the linked specification; this file controls how implementation work is prepared, executed, reviewed, and evidenced.

## Read Order

Before changing files, read:

1. `AGENTS.md`
2. `GOALS.md`
3. `CONTEXT.md`
4. `PLANS.md`
5. the single active file under `harness/build/`
6. any phase-specific material under `harness/context/`
7. `harness/build-log.md`
8. the relevant source files and tests

Do not treat a roadmap item as permission to implement it. Only an explicitly approved phase is active.

## Current State

- Repository foundation is complete.
- Phase 00B, canonical contracts and contract verification, was squash merged to `main` as `98a7514`.
- Phase 01A was independently reviewed and squash merged to `main` as `f7f3cf7`.
- Phase 01B simulator breadth and benchmark is complete, independently reviewed, and validated by the repository phase gate.
- Phase 02 Data Factory and trajectory pilot was independently reviewed, passed CI/GitGuardian, and was squash merged to `main` as `f45b1ea` through PR #6. Its human review sample remains `pending_human` and `training_ready=false`.
- Phase 03A0 Fast/Slow architecture and acceptance-criteria gate was independently reviewed, passed CI/GitGuardian, and was squash merged to `main` as `54afcb8` through PR #7.
- Phase 03A1-H deterministic multi-turn Harness was squash merged as `e08c9b6` through PR #8.
- Phase 03A1-B untuned Qwen/Terra baselines completed its frozen model matrix, independent review, and PR #9 CI/GitGuardian gates.
- Phase 03A1-E evaluation erratum and leakage-safe second run completed its local/independent gates with an honest terminal Provider blocker and passed PR #10 CI/GitGuardian. Its r3 report is a source-bound offline re-attribution of immutable r2 evidence, not a retry or training run.
- Phase 03A1-R hosted baseline reliability rerun completed its full corrected r4 matrix. The original unsupported `oneOf`/`discriminator` attempt is preserved separately; the canonical r4 uses OpenAI-supported `anyOf`, has complete usage accounting, and records `phase_completion_ready=true`.
- Phase 03A1-V evaluation-validity smoke completed its six-episode diagnostic. With the same Qwen/Terra models, prompt/input parity improved the selected baseline from 0/6 to 5/6 end-to-end valid; the remaining fee case exposes a hidden evaluator predicate. Its r5 artifact is diagnostic evidence, not a training or quality gate.
- No implementation phase is active. The next bounded phase requires explicit user approval.
- Phase 03B model training/data expansion, product services, external channels, and web UI remain inactive and require new explicit gates.
- Product services, model training, external channels, and web UI are not implemented.

## Working Rules

- Keep at most one implementation phase active.
- Use the smallest change that satisfies the active phase acceptance criteria.
- Do not begin the next phase automatically after completing the current one.
- Preserve existing user work and unrelated changes.
- Once the user approves a bounded phase or repository change, Sol may create its branch, commit, push, open and review its pull request, squash merge it, and clean up its fully merged short-lived branch without separate approval for each Git step.
- Explicit user approval is still required to expand scope, activate the next phase, deploy or publish a release, contact real external parties, use credentials, perform destructive operations, force-push, or rewrite shared history. Validated cleanup of a fully merged short-lived branch is the only branch-deletion exception.
- Never add real provider credentials, consumer PII, or production secrets.
- A model may propose an action or completion candidate; deterministic policy and evidence checks own authorization and completion.

## Development Loop

For an approved phase:

1. Preflight: inspect current state, assumptions, dependencies, and dirty files.
2. Red: add or identify the smallest failing check that represents the requirement.
3. Green: implement the minimum code needed to pass it.
4. Refactor: only when it removes demonstrated complexity or duplication.
5. Verify: run focused checks, then the broader checks justified by risk.
6. Review: use an independent reviewer for material code or contract changes; the reviewer supplies findings and a recommendation to Sol.
7. Remediate: fix accepted findings and rerun affected checks.
8. Evidence: append pre-merge commands and outcomes to `harness/build-log.md`.
9. Publish: for the approved scope, Sol may commit, push, and open the pull request.
10. Integrate: Sol reviews the final diff, verification, independent-review evidence, and CI, then makes the final approve or request-changes decision and squash merges when the gate passes.
11. Stop: report the phase gate; wait for approval before expanding scope.

Never report a check as passed if it was not run. Separate passed checks from blocked, skipped, manual, browser, cloud, GPU, voice, and external-channel checks.

## Skill Routing

- `karpathy-guidelines`: default discipline for implementation and refactoring.
- `codebase-design`: contract boundaries, deep modules, and interface placement.
- `domain-modeling`: changes to the ubiquitous language in `CONTEXT.md`.
- `code-reviewer`: independent local-diff or pull-request review.
- `diagnosing-bugs`: failures, regressions, and performance diagnosis.
- `vercel-react-best-practices`: React/Next.js implementation or review.
- `design-taste-frontend`: user-approved frontend product work.
- `update-docs` or `write-dev-spec`: documentation affected by code or design decisions.

The installed `fix` skill assumes Yarn commands that this pnpm/uv repository does not use. Do not invoke it automatically; use repository-native checks instead.

## Git Workflow

- Treat `main` as the last integrated, validated state; do not implement or commit directly on it.
- Use one short-lived branch per phase, feature, fix, documentation change, or experiment, following `CONTRIBUTING.md` naming rules.
- Keep one bounded concern per pull request and do not begin the next phase in the same branch.
- Run `make preflight`, review the complete diff, and obtain any required independent review before merge.
- Prefer squash merge so `main` keeps one clear commit per bounded change. Deleting the short-lived source branch is routine cleanup only after Sol confirms the PR is merged, the worktree is clean, the branch was pushed, and no unique unpushed work would be lost.
- For a user-approved bounded phase or change, Sol owns branch creation, commit, push, PR creation, final review, and merge. These routine Git steps do not require separate user review or authorization.
- Never deploy, publish a release, force-push, rewrite shared history, delete an unmerged branch, or perform another destructive Git operation unless the user explicitly requests that exact operation.

## Agent Roles

The root orchestrator uses Sol for architecture, integration, trade-offs, and final decisions. Sol decides when subagents materially improve implementation speed, independent evidence, or review quality; the user does not need to request delegation explicitly.

- `implementer`: Luna xhigh, write-enabled, one clearly owned and well-specified implementation slice.
- `reviewer`: Terra, read-only, independent acceptance-criteria and diff review.
- `fast-worker`: Luna, write-enabled, narrow mechanical or repetitive tasks only.
- `explorer`: Luna, read-only, bounded repository discovery.

Rules for delegated work:

- At most three subagents run concurrently.
- Delegate only concrete, bounded work with a useful independent execution path; Sol may work directly when delegation would add no value.
- Assign explicit, non-overlapping file ownership.
- Tell write-enabled agents they are not alone in the repository and must not revert other edits.
- The implementing subagent does not review or approve its own work.
- Independent reviewer conclusions are evidence and recommendations; they do not merge changes or replace Sol's judgment.
- The root Sol orchestrator reviews and integrates subagent output, owns the final verification statement, makes the PR approval decision, and executes merge when the gate passes.
- Luna max is an explicit per-task escalation for complex multi-file implementation after architecture and acceptance criteria are frozen; it is not a standing default.
- Sol retains decisions about shared architecture, authorization policy, canonical contract semantics, and phase completion. Luna may implement those decisions but must not invent them.

## Repository Verification

Use the checks that exist for the current phase:

```bash
make preflight
make check-layout
uv lock --project runtime --check
pnpm install --lockfile-only --ignore-scripts --offline
docker compose config --quiet
git diff --check
```

Phase 00B established repository-native lint, type-check, unit-test, schema-generation, and contract-drift commands. Later phases must extend the gate only for behavior they actually add.

## Harness Boundaries

- `harness/build/`: executable phase contracts, one file per phase or gate.
- `harness/context/`: small, phase-specific evidence that does not belong in product docs.
- `harness/code_review/`: durable review artifacts for material gates.
- `harness/build-log.md`: append-only execution evidence and phase status.

The Codex development harness is not the product evaluation harness. Simulator scenarios, model evaluations, reward logic, and benchmark artifacts belong under `ml/`, `runtime/`, `data/`, or `tests/` as defined by the architecture.
