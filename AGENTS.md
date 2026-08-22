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
- Phase 00B, canonical contracts and contract verification, is in progress on `feat/phase-00b-contracts`.
- Resolve and record the six required preflight decisions before writing domain models.
- Product services, model training, external channels, and web UI are not implemented.

## Working Rules

- Keep exactly one implementation phase active.
- Use the smallest change that satisfies the active phase acceptance criteria.
- Do not begin the next phase automatically after completing the current one.
- Preserve existing user work and unrelated changes.
- Do not commit, push, publish, deploy, or contact external parties without explicit user approval.
- Never add real provider credentials, consumer PII, or production secrets.
- A model may propose an action or completion candidate; deterministic policy and evidence checks own authorization and completion.

## Development Loop

For an approved phase:

1. Preflight: inspect current state, assumptions, dependencies, and dirty files.
2. Red: add or identify the smallest failing check that represents the requirement.
3. Green: implement the minimum code needed to pass it.
4. Refactor: only when it removes demonstrated complexity or duplication.
5. Verify: run focused checks, then the broader checks justified by risk.
6. Review: use an independent reviewer for material code or contract changes.
7. Remediate: fix accepted findings and rerun affected checks.
8. Evidence: append commands and outcomes to `harness/build-log.md`.
9. Stop: report the phase gate; wait for approval before expanding scope.

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
- Run `make preflight`, review the complete diff, and obtain any required independent review before requesting merge.
- Prefer squash merge and delete the merged branch so `main` keeps one clear commit per bounded change.
- Branch creation, commit, push, PR creation, merge, deployment, and publication still require explicit user authorization. Never force-push or rewrite shared history unless the user explicitly requests the exact operation.

## Agent Roles

The root orchestrator uses Sol for architecture, integration, trade-offs, and final decisions. Delegate only when the user explicitly asks for delegation or parallel agents.

- `implementer`: Luna xhigh, write-enabled, one clearly owned and well-specified implementation slice.
- `reviewer`: Terra, read-only, independent acceptance-criteria and diff review.
- `fast-worker`: Luna, write-enabled, narrow mechanical or repetitive tasks only.
- `explorer`: Luna, read-only, bounded repository discovery.

Rules for delegated work:

- At most three subagents run concurrently.
- Assign explicit, non-overlapping file ownership.
- Tell write-enabled agents they are not alone in the repository and must not revert other edits.
- The implementing agent does not approve its own work.
- The root orchestrator integrates results and owns the final verification statement.
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

Phase 00B must add repository-native lint, type-check, unit-test, schema-generation, and contract-drift commands before it can pass.

## Harness Boundaries

- `harness/build/`: executable phase contracts, one file per phase or gate.
- `harness/context/`: small, phase-specific evidence that does not belong in product docs.
- `harness/code_review/`: durable review artifacts for material gates.
- `harness/build-log.md`: append-only execution evidence and phase status.

The Codex development harness is not the product evaluation harness. Simulator scenarios, model evaluations, reward logic, and benchmark artifacts belong under `ml/`, `runtime/`, `data/`, or `tests/` as defined by the architecture.
