# Sol-Governed Agent and Merge Workflow Review

**Target**: `chore/sol-governed-agent-workflow` working tree against `main` at `f7f3cf7`

**Reviewer**: independent read-only `reviewer` subagent (`gpt-5.6-terra`, high reasoning)

**Final recommendation**: Approve. No unresolved blocking findings remain.

## Scope reviewed

- Sol's authority to select and coordinate bounded subagents without per-delegation user approval;
- separation between subagent implementation/review roles and root Sol integration authority;
- routine branch, commit, push, pull-request, final-review, squash-merge, and merged-branch cleanup rules;
- preserved user gates for phase activation, scope expansion, deployment, release publication, real external contact, credentials, destructive operations, force-push, and history rewrites;
- consistency across repository instructions, reusable prompts, contribution workflow, harness lifecycle, agent configuration, PR template, and status evidence.

## Initial findings and resolutions

### P1 — Reusable prompts retained the old delegation gate

`PROMPTS.md` still said delegation was allowed only when the user explicitly requested it and unconditionally prohibited root Git integration.

**Resolution**: root templates now follow the Sol-governed policy after a bounded phase or change is approved. Delegation templates are selected by Sol when useful. Every subagent template still prohibits commit, push, GitHub review submission, and merge.

### P1 — Merged-branch cleanup conflicted with the destructive-operation gate

The initial policy required source-branch deletion after merge without defining whether that deletion was a routine Git step or a destructive action.

**Resolution**: cleanup is routine only after Sol confirms the PR is merged, the worktree is clean, the branch was pushed, and no unique unpushed work would be lost. Deleting unmerged work remains destructive and requires explicit user authorization.

## Independent verification observed

- Restricted-sandbox `make preflight` initially failed because uv could not read `/Users/edison/.cache/uv/sdists-v9/.git`; the reviewer classified this as an environment permission failure, not a repository check failure.
- With extended read access, `make preflight` passed with 26 tests plus Ruff, mypy, contract drift, TypeScript, layout, lock, compile, and Compose checks.
- `git diff --check` and cached-diff check passed.

## Final responsibility model

The user approves which phase or bounded change is active and retains authority over scope expansion and high-impact external actions. Sol decides whether and how to delegate, reviews and integrates subagent work, owns the final verification and pull-request decision, and squash merges when required evidence and CI pass. Independent reviewers advise Sol and cannot edit, publish, or merge.
