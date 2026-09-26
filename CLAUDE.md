@AGENTS.md

## Claude Code mapping (adds no rules; `AGENTS.md` wins on conflict)

**Root session.** The main conversation is the root orchestrator. It owns `PLAN.md`, the contract, ADRs, `evidence/`, `docs/claims.yaml`, every merge and every stage gate. It never delegates the final diff review, a completion claim or a stage close. The user closes stages.

**Agents** (`.claude/agents/`):
- `implementer`: one task, one worktree, owned paths only.
- `reviewer`: fresh context, read-only, the mandatory fields from PLAN §0.4.
- `architect`: root-only escalation, for a contract or semantics question, or a bug that survived one diagnosis pass.
- The built-in `Explore` is for quick lookups.

**Concurrency.** ≤ 2 implementers per lane and ≤ 4 in flight in total; reviewers are extra.

**Packets.** Use `.claude/task-packet-template.md`: the task block verbatim, `NORTH_STAR.md`, ≤ 5 named files, the verification commands and the escalation triggers.

**Root-run flags.** L (keys in `.env`), G (Modal GPU) and U (the user) are executed by the root, never by a subagent. Implementers get `evidence/` bundles via `tests/support/recorded.py`.

**Git.** Once the user approves a stage, the root may branch, commit, push and open PRs. **Every squash merge into `main` needs the user's go** (the user's standing rule, 2026-09-26), given only to PRs that pass review, CI and the reality rule, unless the user grants merge authority for a stage and `PLAN.md` records it. A stage close, a publish, a contract change after `semantics-v1`, the unseal, the split draw and anything destructive need the user.

**Checks.** Use the `make` targets in `AGENTS.md`. Never report a check as passed without its output. Report passed, failed, skipped, root-run-pending and manual checks separately.

**Skills.** `karpathy-guidelines` (implementation), `diagnosing-bugs` (failures), `codebase-design` (seams and contract questions, root and architect only). Commit and PR creation are root actions.
