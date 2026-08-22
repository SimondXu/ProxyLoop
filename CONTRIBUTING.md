# Contributing to ProxyLoop

ProxyLoop uses short-lived branches and reviewable pull requests to keep `main` stable and the phase history easy to understand. The repository is currently a portfolio project, but the same workflow applies to human and Codex contributions.

## Main Branch Policy

- Treat `main` as the last integrated, validated state.
- Do not implement, commit, force-push, or rewrite history directly on `main`.
- Start work from an up-to-date `main` and merge through a pull request.
- Prefer squash merge so one bounded change produces one clear commit on `main`.
- Delete the source branch after merge.
- Never merge secrets, real consumer PII, provider credentials, generated model weights, local datasets, recordings, or machine-specific state.

GitHub branch protection should eventually require a pull request and passing CI for `main`. A mandatory approval count can be added when the repository has another regular reviewer; it is optional for a solo portfolio repository.

## Branch Naming

Use a lowercase Conventional Commit-style prefix and a short kebab-case description:

```text
feat/phase-00b-contracts
feat/phase-01-provider-simulator
fix/contract-schema-drift
docs/update-architecture
chore/development-harness
experiment/qwen-lfm-smoke-benchmark
```

Use one branch for one phase, feature, fix, documentation change, or experiment. Do not mix unrelated work or begin the next roadmap phase in the same branch.

## Development Workflow

1. Update local `main` without rewriting local work.
2. Create a descriptive branch from `main`.
3. Read `AGENTS.md`, `GOALS.md`, `CONTEXT.md`, `PLANS.md`, and the active `harness/build/phase-*.md` file.
4. Make the smallest change that satisfies the approved scope.
5. Run focused checks while developing.
6. Run the repository preflight before commit:

   ```bash
   make preflight
   ```

7. Review the complete diff and confirm that generated, sensitive, local, or unrelated files are absent.
8. Commit with a Conventional Commit message.
9. Push the branch and open a pull request using the repository template.
10. Resolve review findings and rerun affected checks.
11. Squash merge only when required checks and phase acceptance criteria pass.
12. Delete the merged branch and start later work from the updated `main`.

## Commit Messages

Use:

```text
<type>(<optional-scope>): <imperative summary>
```

Common types:

- `feat`: product or platform capability;
- `fix`: defect correction;
- `test`: test-only change;
- `docs`: documentation-only change;
- `refactor`: behavior-preserving code change;
- `chore`: repository, tooling, or harness maintenance;
- `experiment`: isolated research or benchmark work.

Examples:

```text
chore(harness): add phase-gated Codex workflow
feat(contracts): add versioned approval models
fix(simulator): reject stale provider offers
```

## Pull Request Scope

Every pull request should explain:

- the problem and bounded outcome;
- files or systems intentionally changed;
- explicit non-goals;
- verification actually run and its result;
- manual, blocked, skipped, or unrun checks;
- security, privacy, data, migration, and rollback risks;
- whether documentation, generated artifacts, or phase evidence changed.

Material contract, security, authorization, completion, workflow, or external-channel changes require an independent review. The implementation agent must not approve its own work.

## Versioned and Local Content

Version project source, tests, small redacted fixtures, schemas, documentation, `.codex/` project configuration, and curated harness evidence.

Keep local or generated content out of Git: `.env*`, dependency directories, virtual environments, caches, coverage output, local databases, provider credentials, PII, raw datasets, model weights, checkpoints, experiment stores, recordings, and large artifacts. Add a specific `.gitignore` rule when a new tool creates repeatable local output; do not hide an entire source or configuration directory to silence an unclear change.
