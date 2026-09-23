@AGENTS.md

## Claude Code

This section maps the shared contract above onto Claude Code. It adds nothing to the rules; it only names the tool-specific mechanisms. When this section and `AGENTS.md` disagree, `AGENTS.md` wins.

### Root session and roles

- The main conversation is the root orchestrator. It owns every root-orchestrator-retained decision in `AGENTS.md`, inspects primary evidence itself, and never delegates the final diff review, completion claim, or integration decision.
- Project roles are `.claude/agents/explorer.md`, `fast-worker.md`, `implementer.md`, `reviewer.md`, and `architect.md`. Spawn them with the `Agent` tool by name; every task packet must carry the objective, scope and non-goals, known paths, owned files or exact questions, expected output, verification command, and escalation triggers.
- Concurrency ceiling: 6 subagents in flight at once, matching `max_concurrent_threads_per_session` in `.codex/config.toml`. This is a ceiling, not a target; it overrides the lower global default for this repository.
- `architect` runs on Opus at `high` effort (switched from Fable on 2026-09-23 at the user's direction: Opus 5.5 is currently the stronger model for this role). Use it only for a root-orchestrator-retained decision that needs a worked proposal (architecture, interface placement, canonical contract or evaluator semantics, a durability or concurrency design) or for a bug that survived one `diagnosing-bugs` pass. It returns a proposal or diagnosis with evidence; the decision stays in the main session. Do not use it for ordinary implementation.
- `explorer` and `reviewer` are read-only by contract and tool list. They are not sandboxed the way Codex `read-only` agents are, so never hand them a task that expects edits.
- The global agents `root-cause-investigator`, `silent-failure-hunter`, `test-log-analyzer`, `security-auditor`, and the built-in `Explore` remain available for their own triggers. Use `explorer` when the output must be an evidence card tied to the active phase; use `Explore` for a quick unbounded lookup.
- There is no `.codegraph/` index in this repository; explorers use `Grep`, `Glob`, and focused reads.

### Model mapping from the Codex configuration

| Role | Codex | Claude Code |
|---|---|---|
| root orchestrator | `gpt-5.6-sol` high | main session (whatever model the session runs) |
| `explorer` | Luna medium | `sonnet`, `effort: medium` |
| `fast-worker` | Luna medium | `sonnet`, `effort: medium` |
| `implementer` | Luna xhigh | `inherit`, `effort: high` |
| `reviewer` | Terra high | `opus`, `effort: high` |
| `architect` | Luna max (escalation only) | `opus`, `effort: high` |

### Orientation

Follow the `AGENTS.md` orientation order. In practice: `harness/status.toml` → the active `harness/build/phase-*.md` if any → only the source and tests the task names. Do not read `harness/build-log.md` (144 KB) unless a named historical claim requires it.

### Verification commands

Repository checks are `make` targets; the installed `fix` Skill (Yarn) does not apply here.

- Focused: `make lint`, `make typecheck`, `make test`, `make format`, `make web-check`
- Fast gate while iterating: `make preflight-fast`
- Final local gate, run once on the stable diff: `make preflight` = `validate` (`format-check`, `lint`, `typecheck`, `test`, `check-layout`, `web-check`) + `lock-check` + `python3 -m compileall -q scripts` + `docker compose config --quiet`. With `PROXYLOOP_TEST_DATABASE_URL` unset it exits 0 while skipping the DB/Temporal tests in `test_phase_04c_persistent_case_store.py`, `test_phase_05a_case_runtime.py`, `test_phase_05a_temporal_workflow.py`, and `test_phase_06b1_temporal.py`, so it does not cover them. A change under `case_runtime`, `workflow_worker`, `connectors`, or `api` also needs the real-dependency gates below.
- Real-dependency gates (need the Compose PostgreSQL/Temporal profiles; they fail rather than skip without their variables): `make postgres-check` (`PROXYLOOP_TEST_DATABASE_URL`), `make phase05a-check` and `make phase06b1-check` (`PROXYLOOP_TEST_DATABASE_URL` and `PROXYLOOP_TEST_TEMPORAL_ADDRESS`). The URL must name the `proxyloop_test` database. Run them serially and from one worktree at a time: they share `proxyloop_test`, truncate its tables, and reuse fixed Case and command ids, so concurrent runs (including a `make preflight` with the variables set) truncate each other and fail intermittently. Details: `docs/development.md`, "Local gate and real-dependency gates".

Report passed, failed, blocked, skipped, manual, and unrun checks separately. Never claim a check passed without its output.

### Built-in commands and skills

- `/code-review`: allowed as a mid-development pass on the working diff. It does not replace the phase-gate independent review, which is the `reviewer` agent's recommendation recorded by the root orchestrator under `harness/code_review/`.
- `/simplify`: refactor-only cleanup after the diff is green; keep it inside the approved scope.
- `/security-review`: quick scan for contract, authorization, channel, or credential-adjacent changes; a deep audit goes to `security-auditor`.
- `commit-commands:commit`, `commit-commands:commit-push-pr`, `pr-creator`: use these for the routine Git steps below; PR bodies must fill `.github/pull_request_template.md`.
- Skill names in `AGENTS.md` that differ here: `design-taste-frontend` → `frontend-design`. All other listed skills exist under the same names.

### Git steps in Claude Code

`AGENTS.md` lets the root orchestrator run the routine Git workflow through squash merge once a phase is approved. In Claude Code the phase approval is the request that authorizes branch creation, commits, push, and opening the pull request; do not ask again for each of those. Stop after the PR is open and CI plus independent review are reconciled, report the state in one message, and squash merge and delete the merged branch only after the user says go. This is deliberately one step stricter than the Codex contract because merge to `main` is the single irreversible step and the desktop app already surfaces the PR for that decision.

### Evidence

- One log per bounded change under `harness/log/`, updated only at verification boundaries.
- Review artifacts under `harness/code_review/`; The root orchestrator writes them from the `reviewer` agent's findings.
- Return `harness/status.toml` to `idle` at the gate and stop; the next phase is a new user decision.
