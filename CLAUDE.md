@AGENTS.md

## Claude Code workflow (operating model v4, user decision 2026-10-11; `AGENTS.md` wins on conflict)

**One session** plans, writes code and docs, runs checks and live smokes, opens PRs and merges. No lane leads, model root, charters, teammates, cross-session messages or lane logs. The previous multi-session rules are at tag `plan-v3-process-final`.

**Session start.** Read `PLAN.md` (NORTH_STAR and AGENTS are loaded). State the milestone and the next step in one line.

**Outcome first.** Until M1 (`PLAN.md`), every PR on the session path names the trajectory step it unblocks and the run id that shows the block. Other work waits in PLAN "Frozen", except invariant or security fixes, run-breaking infra and docs.
- **Stop rule:** 3 merged PRs aimed at one step, or 5 session-path PRs in total, without the furthest step advancing on a clean live run → stop coding and write a one-page rethink for the user (reachable with a scripted Slow? model capability? design?). Only the user changes these numbers. This rule stops work to think; it is not the "metric must rise every N PRs" tripwire that `NORTH_STAR.md` lists as a non-goal, and it never rejects a PR.
- **A run counts** only if it is infra-clean (no `world_error`, `llm_unavailable` or provider timeout) and each role ran with its intended model, provider and effort (served echo, reasoning tokens). Report infra ends separately; two in a row → fix infra first.
- **Live smokes:** one factor at a time, a stated hypothesis and target step, ≥ 3 runs before concluding (5 when they disagree); run from `../pl-wt/smoke` detached at the sha under test. Read the transcript around the furthest step yourself.

**Who writes.** You write docs, PLAN, ADRs, config, scripts, tests and code up to ~300 changed non-test lines, on a `task/<id>` branch in the main checkout. Use an `implementer` (Sonnet 5.5; pass `model: opus` for Tier C) for larger or mechanical multi-file work, or to work while a smoke runs. Brief it with `.claude/task-packet-template.md` and create its worktree with `scripts/root/new_worktree.sh`. Parallel implementers work on disjoint packages.

**Review.** Tiers and blocking rules are in `.claude/agents/reviewer.md`. Only blockers block; there is no follow-up list.

**Experiments and evals.** A paid experiment states first which decision it changes and what result would change it, stays ≤ $10 per run/batch (more → ask the user), and stops once the answer is clear. Pre-registration and blind judging only for claims (S3/S4) and held-out data. Never use `principal-architect` or Opus subagents as annotators, judges or for batch work; `principal-architect` is for a stop-rule rethink or a hard design question, `architect` for contract or semantics questions.

**Checks and CI.** Focused `uv run pytest <path> -q`, then `make check-fast 2>&1 | tail -40` (full `make check` for concurrency/fences). Never paste full logs. Wait for CI with one background command, never a polling loop:
`gh pr checks <PR> --watch --required --fail-fast -i 30 >/dev/null 2>&1; scripts/root/merge_gate.sh check <PR> | tail -1`

**Git.** Branch `task/<id>` from `origin/main`; PR title `<ID>: <title>`; the PR body holds the spec, the evidence and the reality statement. Merge with `scripts/root/merge_gate.sh merge <PR>` when CI is green and the tier's review has no open blocker. Squash only; never `--admin`, `--auto` or force; confirm MERGED before deleting a branch. Branches live < 1 day; merge `origin/main` into a branch only on path overlap.

**State.** `PLAN.md` (≤ 120 lines) is state, not a log: milestone, trajectory ledger, Now/Next (≤ 7), Frozen, Waiting on the user, standing decisions. Update it inside the PR that changes it; there are no sync PRs. One-page ADRs only for the contract, metric semantics or model roles. Project memory holds only durable constraints and user preferences (≤ 10 entries).

**Context.** When a task is done, update PLAN Now/Next and `/clear`. If a task reaches ~400k tokens of context, first write the current findings and hypotheses into PLAN or the PR body, then `/clear` and continue. Send broad searches to `scout` and deep dives to `root-cause-investigator`; use their conclusions, not their logs.

**Ask the user** (batched, as concrete scenarios): spend above $10 per run/batch or beyond a stage budget (TeamRouter standing rule: report only when the balance runs out); any change of a product role's model or effort; contract changes after `semantics-v1`; the split draw, the unseal, pre-registration and publishing; anything irreversible, data loss or secrets; stage closes and U steps; changes to these rules, `.claude/settings.json`, hooks or `NORTH_STAR.md`. Decide everything else yourself and list it under "Decisions" in your next message.

**Subagents.** `implementer`, `reviewer`, `scout`, `architect`; user-level `root-cause-investigator`, `test-log-analyzer` (sonnet) and `principal-architect` (see "Experiments and evals").

**Guardrails.** `.claude/settings.json` and `.claude/hooks/` block destructive commands, `.env` reads, and subagent edits outside their grant (AGENTS rule 16). A permission refusal is final.
