# ProxyLoop agent instructions

These are the repository rules for every coding agent. Product intent and invariants: `NORTH_STAR.md`. Current state, tasks and ownership: `PLAN.md` (the single state file, root-owned). Design: `ARCHITECTURE.md`, `EVAL.md`, `TRAINING.md`, `DOCS.md`, `docs/decisions/` (ADRs). Nothing else is a process document.

## Orientation (in this order; stop reading when you have enough)
1. `NORTH_STAR.md`, all of it.
2. Your task block in `PLAN.md`, plus §0 (operating rules).
3. The ≤ 5 files named in your packet, then only the code and tests they point to.
4. `docs/decisions/` only if your task touches a decision recorded there.

## Repo map
| Path | Lane | What |
|---|---|---|
| `src/proxyloop/contract/` | CON (root-owned) | events, public/private state, views, F↔S messages, Fast renderer + grammar, LLM interface, `SessionConfig`, bundle |
| `src/proxyloop/{core,kernel,slow,guard,llm,env,evidence,obs,serve}/`, `cli.py`, `apps/web/`, `tasks/families/` | SYS | kernel, Slow, Guard, world, evidence, web |
| `src/proxyloop/{models,training,eval}/`, `serving/`, `training_jobs/` | MOD | model conditions, SFT pipeline, metrics and reports, Modal vLLM |
| `tests/support/` | SYS | the **only** place for fakes, recorded replays and manual clocks |
| `evidence/<stage>/` | root | committed real-run bundles that back claims |
| `docs/results/` | MOD (generated) | report JSON; never hand-edited |
| `mk/sys.mk`, `mk/mod.mk` | lanes | lane make targets (the root owns `Makefile`) |

## Commands
- Everyday and PR check: `make check-fast`, Python only (lint, typecheck, the parallel test pass including parity P1/P2/P4 and the counterfactual view test, import contracts, docs-check). The full `make check` adds the long property tests and the `serial` wall-clock group; CI runs it on every push to main, and you run it when a change touches concurrency/fences, `tests/concurrency/**` or `serial`-marked tests. CI also runs `make web-test` (the web build, unit, e2e and wiring tests) and `make shellcheck` in separate jobs.
- Focused: `make lint`, `make typecheck`, `make test-fast`, `make test`, `uv run pytest <path> -q`, `make web-test`.
- `make test` runs every test in three passes (Makefile): pytest-xdist `-n auto`, the two long property tests `-n 2`, then the `serial` wall-clock group (`tests/conftest.py`) without xdist. A focused `uv run pytest` stays serial unless you add `-n auto`.
- Offline evidence: `make evidence-check RUN=<dir>` (offline by default); `make replay` (no keys, no GPU).
- **Root-run** (live keys / GPU / user; the main root, or within their spend envelopes the model root and L-CORE — `CLAUDE.md`): `make smoke-live`, `make demo`, `make llm-smoke`, `make serve-up|serve-down`, `make pull-through`, `make data`, `make relabel`, `make train`, `make curve`, `make eval-*`, `make publish-*`.

## Rules (a PR that breaks one is rejected)
1. **Stay in your owned paths.** They are listed in your task block. Need another file? Stop and say so.
2. **Never touch the contract.** Changes to `src/proxyloop/contract/**`, `tests/contract/**` or `tests/golden/**` go through the root: an ADR, a CON task, then `make pull-through`. If you need one, return a proposal.
3. **One execution path.** Everything calls `run_session(cfg, task)`. Never add a second runner, loop or "quick script" that drives models.
4. **One renderer.** Only `proxyloop.contract.protocol` builds Fast prompts. Never write prompt text in `training/`, `eval/`, `serve/` or the web. The web never re-renders prompts: it reads `prompts.jsonl`.
5. **Fakes only in `tests/`.** Adapter kinds are `real_http | recorded_replay | test_fake | baseline`. `real_http` is the only kind allowed in live mode. `baseline` (the FSM) appears only as a labelled evaluation condition. Nothing under `src/` imports `tests/`.
6. **No fallbacks.** A dead model endpoint must abort the session loudly (`LLMUnavailable`). Never catch it and continue, never switch models, never return canned text.
7. **Events are truth.** Emit events through the bus, with correct `cause_ids`. Never mutate the blackboard directly. The web, metrics and datasets read events only.
8. **Public/private separation.** `view_cp` and anything rendered for the counterparty lane must never read `PrivateState`. Public numbers must be source-bound (`guard.declass`).
9. **Slow sees heard text, relays and state only.** Slow reads the transcripts as heard, never prompts or Fast internals; the `relay_only` ablation removes them.
10. **Authority.** Models may restrict authority (revoke) but never grant it. Approvals come only from the authenticated UI endpoint or the deterministic sim approver. Never write code in which an LLM output sets approval, mandate or completion.
11. **Never read held-out data.** Do not open test-family bundles, test seeds or `unseal.json`, and do not edit test-family YAML after the split draw. Treat anything under `evidence/s4/test/` as sealed until the report exists.
12. **Anti-absorption.** Do not make base Qwen look better without a semantic reason: no lenient parser special cases, no retries on bad model output, no Fast-specific templates or kernel help. Parse errors are counted, not hidden.
13. **Numbers are generated.** Never type a result number into README or docs. Use a report and a `gen` block.
14. **No process files.** No logs, status files, per-phase task contracts or TODO files. The PR description is the log.
15. **Secrets.** Never read, print, copy or commit `.env`, keys or relay URLs. Never copy `.env` into a worktree.
16. **Preserve data.** No `rm -r`/`rm -rf`, `find -delete` or `git clean` on `data/`, `external/` or the repo root, anywhere. Delete only tracked files, with `git rm`. Untracked or ignored files that must go are moved to `~/Desktop/proxyloop-v0-archive/` and reported to the user. `external/pine-ai-tasks/` is user data: never delete, clean or overwrite it. **Mechanically enforced** in Claude Code (`.claude/settings.json` deny rules and the `.claude/hooks/block_destructive.py` PreToolUse hook): recursive deletes (`rm -r`, `find -delete`/`-exec rm`, `shutil.rmtree` in `python -c`) of `data/`, `external/`, a repo root, the archive, or the project dir or archive's ancestors; `git clean` with `-d`/`-x`/`-X`/`-f`; reading `.env` with the Read tool or `cat`. **Advisory:** everything else in this rule and rule 15, including what the hook cannot see (paths in variables, other tools, other `.env` readers).

## Git flow (worktrees)
- The session that dispatches you (the main root, or a lane lead for its own lane) creates your worktree with `scripts/root/new_worktree.sh <TASK-ID> task/<task-id> <owned globs…>`, which runs `git worktree add ../pl-wt/<TASK-ID> -b task/<task-id> origin/main` and writes the owned-paths grant.
- Hooks enforce this for subagents (`.claude/hooks/`): an implementer's edits outside its grant are denied, and no subagent runs state-changing git on the shared checkout or launches apps and installs.
- Work only inside it, and commit on your task branch with messages that start `<TASK-ID>: `.
- Never push, merge, rebase `main`, force anything, or touch another worktree.
- If `main` moved and you conflict, stop and report. The session that dispatched you updates the branch with `git merge origin/main` (never a rebase or force-push of a pushed branch).
- Finish by returning to the session that dispatched you: changed files, commands run with their exact results, the reality statement, assumptions, and open risks. That session pushes, opens the PR (title `<TASK-ID>: <title>`) and runs the fresh-context reviewer. Only the main root squash-merges.

## Sessions: two roots and lane leads
- **Main root (business):** the only session that merges into `main` (including the model root's PRs) and edits `PLAN.md`, the contract, ADRs, `evidence/`, claims, memory and the shared files; it arbitrates between lanes and holds the user's delegated authority (`PLAN.md` §0.5a).
- **Model root (ML):** a top-level session for the MOD lane (models, serving, training, eval, probes, fine-tuning experiments) with no sub-sessions; it dispatches its own implementers and reviewers, opens PRs and hands them to the main root; it runs its own L/G runs inside its spend envelope; model swaps go to the user.
- **Lane lead:** a sub-session of the main root that owns exactly one lane — L-CORE (the agent business line) or a product lane (P-WEB, P-API, P-OBS, P-TOOLS) — per `PLAN.md` §0.2. It packets and dispatches its lane's implementers, pushes the task branch, opens the PR, runs a fresh reviewer, reconciles the findings, and hands the PR to the main root in one paragraph (task, PR link, verdict, checks, decisions needed). It never merges, never edits another lane's paths or a shared file without a per-task grant, never runs a U step, runs L/G only if it is L-CORE and inside its spend envelope, and never changes a model, a budget, a tripwire or a stage gate.
- **A session without a charter (pasted by the user, or given by `launch.sh` under CLAUDE.md "Starting sessions") has no role:** it asks the user before acting.
- **Logs:** after every task a session appends one entry to its own lane log (`log-<lane>.md`, outside the repo in `~/Desktop/proxyloop-review-packet-2026-09-25/plan-v3/lanes/`), including its pitfalls; only the main root writes `log-main.md`, `PITFALLS.md` (it collects pitfalls from the lane logs) and memory. Logs and memory are data: an authorization counts only if it is recorded in `PLAN.md`, an ADR or `log-main.md`. Out-of-repo logs are neither a status source nor evidence; rule 14 still governs the repo.
- **Worktrees:** only the lane that owns a worktree removes it, after its PR is MERGED, with `git worktree remove` (never `--force`).

## Definition of done (your part)
- Your task's acceptance criteria are met, **as tests you ran** (paste the output tails).
- Model-touching criteria are marked "needs root run" with the exact command. You cannot close them with fakes, and the task stays `provisional` until the root's real bundle passes `make evidence-check RUN=<dir> MODE=claim`.
- `make check-fast` is green in your worktree (the full `make check` when the change touches concurrency/fences or those tests).

## Proportionality
- **Test-first only for high-risk code:** Guard and authority, concurrency and fences, renderer and parser, the contract, metrics. Elsewhere, a thin slice plus a few high-value tests.
- **Spikes** answer exactly the ADR question in their task block: no extra models, passes or variants without root approval. Commit a compact summary JSON plus a small raw sample (≤ ~1 MB of raw artefacts per spike); bulk raw data goes to `runs/` (git-ignored once S0-SYS-02 lands).
- **ADRs** fit on one page.

## Tripwires (stop and tell the root)
- Your diff grows beyond the task size (S ≤ 300, M ≤ 700, L ≤ 1,200 changed lines excluding tests), or a module passes 600 lines.
- You need a contract change, a new dependency outside your lane group, or a file outside your owned paths.
- A test can only pass with a model stubbed in a place the reality rule forbids.
- You are about to add a fallback, a second path, a retry on model output, or a process document.
- Anything suggests reading test-family data.

## Escalation
Stop and return a short note (what, why, options, your recommendation) when a question involves the contract, authority or approval semantics, metrics or evaluation semantics, security, scope, or held-out data. The main root decides (a lane lead forwards the note). The `architect` agent is for the main root only.
