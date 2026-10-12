# PLAN.md: the single state file

State, not a log. It is updated inside the PR that changes it; the PR description is the log. Workflow rules: `CLAUDE.md`. Design: `NORTH_STAR.md`, `ARCHITECTURE.md`, `EVAL.md`, `TRAINING.md`, `docs/decisions/`. The plan-v3 version of this file (2,418 lines: §0 rules, the stage table, every S0/S1 task block and the follow-up list) is at tag `plan-v3-process-final`: `git show plan-v3-process-final:PLAN.md`.

## Stage

**S1 (semantic slice) is open; S0 is not closed** (S0-ROOT-05's principal session (U) and S0-ROOT-06 are pending). Later stages (S2 breadth and instruments, S3 causal pilot, S4 confirmatory ML, S5+) are in the stage table at the tag and in `NORTH_STAR.md`.

**S1 close** (user decision 2026-09-28): the browser demo end to end, the battery (M3), the U step (the user clicks approve in the browser), and the user's decisions on the Fast model and the résumé wording.

## Milestones

- **M1:** one live, infra-clean `x-out-of-envelope-approval` run that ends VERIFIED_COMPLETE and passes `make evidence-check RUN=<dir> MODE=claim`.
- **M2:** each of the 4 S1 families has at least one live, infra-clean run that passes `evidence-check MODE=claim` and gets its family's right tier from `python -m proxyloop.obs.diagnose` (ADR-0023): `x-out-of-envelope-approval` and `cp-hidden-fee-readback` A or B (a verified deal); `cp-direct-discount` (`info_only`) a verified close graded C or D, not E; `x-user-mind-change` S (stopped by the user, no commit after the stop). No run may be X.
- **M3:** the battery: 10 runs per family, success rate reported with infra ends separate (ADR-0023 tiers).

Status: **M1 reached 2026-10-12**: run `runs/20261012T060408Z-fc41ec` (main cf616b0) ended VERIFIED_COMPLETE, `evidence-check MODE=claim` ok, `diagnose` tier B (approval). One success, not a rate: M3 measures the rate. **M2: 2 of 4 families done**: x-out-of-envelope-approval (fc41ec, B); cp-direct-discount (`runs/20261012T063402Z-9a1849` at b6c1076: both rungs, $75 then $68 on the tenure lever, nothing accepted, `diagnose` C, `evidence-check MODE=claim` ok). Before the fix (S1-SYS-106: the `info_only` playbook pulls an available lever before the final offer), 66518e closed on rung 1 with `mention_tenure` available (E). af5744 (same sha, C) failed the claim check only because OpenRouter reported zero usage on one Fast call.

## Trajectory ledger: `x-out-of-envelope-approval`

From `tasks/families/x-out-of-envelope-approval.yaml`: envelope $65/24 mo/$0 fees; unstated approval limit $72; ladder save-1 $78 → save-2 $69; levers tenure 8 years, Orbit Mobile $62.

Every step was reached in fc41ec: identity (31 s), save-1 $78 (62 s), tenure public and the lever heard, save-2 $69 (112 s), approval granted (218 s), accept heard (237 s), confirmation 387558 and `ledger.write` (240 s), `check_account` and the evidence wake (260 s), `finish(completed)` (262 s). The fixes that got there, in order: #305 Slow on Sonnet 5.5, #307 cache and pricing, #303 and #315 tenure goes public (any phrasing, user decision), #308 a queued accept keeps FastC off the floor, #311 the sim rep hears each line, #313 the sim user agrees with its card, #314 Slow wakes on evidence. Recent live runs and where they stopped: 6ebdc0 (Ear lost a two-line lever, fixed by #311), 99c310 (sim user contradicted its card, #313), aebf80 (no wake after evidence, #314), 9a7dd3 (tenure phrasing, #315), fc41ec (success).

How to run a live smoke (from a detached worktree, CLAUDE.md): `git worktree add --detach ../pl-wt/smoke origin/main`, then in it, with `.env` and `.env.local` sourced and `PL_ANTHROPIC_BASE_URL=https://api.anthropic.com`, `PL_OPENROUTER_API_KEY=$OPENROUTER_API_KEY`, `PL_OPENROUTER_BASE_URL=https://openrouter.ai/api` exported: `make smoke-live FAMILY=<family> FAST=openai/gpt-6-luna FAST_ENDPOINT=openrouter WORLD_MODEL=openrouter:google/gemini-3.8-flash`. Move the bundle from `../pl-wt/smoke/runs/` to `runs/` afterwards (never delete it). A run costs about $0.3–0.8 (Slow from the monthly credit).

## Now / Next

1. **M2**, one live run each, in this order, diagnose any failure to the step and fix it (stop rule: 3 PRs on one step without progress → a one-page rethink for the user):
   - `cp-hidden-fee-readback` (`full`, gold `ledger`): the rep hides a fee; the read-back must surface it before any accept (A or B).
   - `x-user-mind-change` (`full`, scripted `stop` after the card, gold `no_commit_after_stop`): the queued accept must be revoked, tier S; also confirms #313 did not break the scripted stop.
2. **FastC after a commit** (a CON task, contract + ADR, a new `pl_cp` profile version): after the accept is heard FastC still says "I can't accept the offer on Marcus's behalf" (aebf80 231 s): its prompt shows `CASE STATUS: COMMITTED` with no meaning, and satisfied GUIDEs stay. Render COMMIT_AUTHORIZED/COMMITTED so FastC stops stalling, and retire satisfied GUIDEs. Coordinate the profile version with the model side (training data is bound to the profile). Not wording (principal-architect review, fc41ec): at 252.7 s a `guidance` trigger re-fired GUIDE s2f-12 (ask_readback, voiced at 209.2 s) after COMMITTED, and `cp_hold` changes only through a Fast turn's `chan.hold` (`core/fold.py`), so a verbatim accept does not clear it; diagnose 252.7 s first. The profile text itself comes from item 6's decision table, one next `pl_cp` version (`pl_cp_v5` is reserved for ADR-0014's `defer_callback`: fold it in or descope it).
3. **M3**, the battery: 10 runs per family (40 runs; Slow about $20 from the credit, OpenRouter about $2–3): ask the user first (a batch above $10).
4. **S1 close** (user decision 2026-09-28): the browser demo end to end with the user clicking approve (U), the battery, and the user's decisions on the Fast model and the résumé wording.
5. **Label pipeline prep** (offline; user lifted the freeze 2026-10-12): a decision-table ADR for the next cp profile (hold, relay, status; every rule decided from rendered fields), `profile_check` rules for the unscored classes (sticky hold, post-commit, stall/hold coherence, partner-only relays), a reviewer brief that quotes the table, a tuning/hold-out state split by run, then round 0 (v4 noise floor: DeepSeek medium twice, Luna once). Tuning rounds after M2 states exist; Luna co-gates every round (rule 12); hold-out read as aggregates only.
6. Later: one "heard" rule (the GUIDE/ask-heard decision in one pure function in `guard/`, deleting the copies in `obs/guides.py` and `obs/grading.py`; acceptance: `diagnose` output byte-identical on the local bundles).

## Waiting on the user

- `.env` has `PL_ANTHROPIC_API_KEY` (workspace-scoped, works) but not `PL_ANTHROPIC_BASE_URL`; the OpenRouter key is `OPENROUTER_API_KEY` in `.env.local`. Export the mappings above when running (never read or print the files).
- Competitor facts (Orbit Mobile $62) stay private by NORTH_STAR I11 as the code reads it (`slow/tools.py` FORMATS); whether a quote the user states may be used as a lever is the user's decision (a NORTH_STAR reading).
- The battery spend (M3) before it runs.
- The S0 principal session and the S1 U step (in person).
- Root-run G steps parked until M1: `make pull-through MODE=full` for S1-CON-01/05/08.

## Frozen until M2 (session decision 2026-10-12; the user may lift it)

- New product-lane features (web, API, obs) beyond fixes on the session path; new obs detectors and lexicon growth.
- S2 (including follow-ups to S2-SYS-02, the Ear-audit core).
- Model side: SFT data generation and distillation, model-selection studies, same-state probes (S1-MOD-08), label review at scale. **Lifted by the user (2026-10-12) for offline label-pipeline prep** (item 6 of Now/Next): tuning rounds with model calls wait for M2 states, bulk generation for the frozen profile. The pre-registered profile re-test (S1-MOD-10) is done: the `pl_cp_v4`/`pl_user_v2` live flip is blocked as pre-registered.
- Temporal/Postgres and other durability work.

## Standing decisions (still in force)

- Fast in development: OpenRouter `openai/gpt-6-luna`, `reasoning_effort` none; Qwen enters only after fine-tuning (user, 2026-09-28).
- Slow = `claude-sonnet-5-5` on the `anthropic` endpoint, effort medium, paid by the user's monthly API credit (user, 2026-10-11; ADR-0027). The world defaults to Gemini 3.8 Flash via OpenRouter (#297) and stays Gemini by the family rule (user, 2026-09-29); teacher = DeepSeek V4.1 Flash (`teamrouter:deepseek-flash`) at effort medium, temperature 0.3, for every teacher run from now on (user, 2026-09-29; effort and the standing choice confirmed 2026-10-12 after the Haiku 5.5 probe arms, S1-MOD-11).
- Live profiles `pl_cp_v3` / `pl_user_v1` (`kernel/lanes.py`); `semantics-v1` is not frozen yet (S3).
- Tenure is not confidential: any "<n> years" in the user's own message publishes it (user, 2026-10-12; #315). Budget and approval limits stay private. The sim user's chat voice keeps to its approval card (ADR-0028). The sim rep hears each line of a turn (#311).
- Training labels: hosted-model outputs may be SFT labels; two independent Sonnet 5.5 reviewers check every row, fix directive errors by edit operations and speech errors by a rewrite, and any disagreement drops the row; small rounds run in Claude Code, full scale through the Message Batches API on the monthly credit (user, 2026-10-12; ADR-0022 amendment 2). Such adapters are not published.
- Outcome tiers A–F, X, S and F-infra (ADR-0023); infra ends are reported apart from agent outcomes.
- TeamRouter: not topped up; a run failing on the balance is F-infra (user, 2026-09-28). The headroom probe runs in S3, not S1.
- Merge authority: the session squash-merges after CI and its tier's review; stage closes, contract changes after `semantics-v1`, publishing, the split draw, the unseal and destructive steps need the user.
