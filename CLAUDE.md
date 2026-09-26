@AGENTS.md

## Claude Code: root session and tool mapping (`AGENTS.md` wins on conflict)

**Root session.** The main conversation is the root orchestrator. It owns `PLAN.md`, the contract, ADRs, `evidence/`, `docs/claims.yaml`, every merge and every stage gate. It never delegates the final diff review, a completion claim or a stage close. The user closes stages.

**The root decides; it never authors.** No files or code, not even for a ROOT task (PLAN §0.1), and no file-writing through Bash heredocs. The root writes only packets and PR bodies; every file is written by an `implementer` whose packet grants the paths.

**Test and CI output.** The root never runs or reads full test, lint or CI output. It spawns the global `test-log-analyzer` (model: sonnet) for `make check`, focused suites and `gh pr checks`, and uses only pass/fail plus the classified failures. Implementers still run their own focused checks.

**Decisions changed.** Any ADR or change that amends `ARCHITECTURE.md`, decisions-v3, a model choice, the budget or the scope goes under a "Decisions changed" heading in the root's next message to the user. A model swap is never made on root authority alone: the user decides.

**Agents** (`.claude/agents/`):
- `implementer`: one task, one worktree, owned paths only.
- `reviewer`: fresh context, read-only, the mandatory fields from PLAN §0.4.
- `architect`: root-only escalation, for a contract or semantics question, or a bug that survived one diagnosis pass.
- The built-in `Explore` is for quick lookups.

**Concurrency.** ≤ 2 implementers per lane and ≤ 4 in flight in total; reviewers are extra.

**Packets.** Use `.claude/task-packet-template.md`: the task block verbatim, `NORTH_STAR.md`, ≤ 5 named files, the verification commands and the escalation triggers.

**Root-run flags.** L (keys in `.env`), G (Modal GPU) and U (the user) are executed by the root, never by a subagent. Implementers get `evidence/` bundles via `tests/support/recorded.py`.

**Git.** Once the user approves a stage, the root may branch, commit, push and open PRs. **Every squash merge into `main` needs the user's go** (the user's standing rule, 2026-09-26), given only to PRs that pass review, CI and the reality rule, unless the user grants merge authority for a stage and `PLAN.md` records it. A stage close, a publish, a contract change after `semantics-v1`, the unseal, the split draw and anything destructive need the user.

**Guardrails.** `.claude/settings.json` denies the common destructive and `.env`-reading commands, and runs `.claude/hooks/block_destructive.py` before every Bash call (AGENTS rule 16 lists what is mechanical and what is advisory).

**Checks.** Use the `make` targets in `AGENTS.md`. Never report a check as passed without its output. Report passed, failed, skipped, root-run-pending and manual checks separately.

**Skills.** `karpathy-guidelines` (implementation), `diagnosing-bugs` (failures), `codebase-design` (seams and contract questions, root and architect only). Commit and PR creation are root actions.
