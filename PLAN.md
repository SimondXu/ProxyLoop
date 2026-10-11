# PLAN.md: the single state file

State, not a log. It is updated inside the PR that changes it; the PR description is the log. Workflow rules: `CLAUDE.md`. Design: `NORTH_STAR.md`, `ARCHITECTURE.md`, `EVAL.md`, `TRAINING.md`, `docs/decisions/`. The plan-v3 version of this file (2,418 lines: §0 rules, the stage table, every S0/S1 task block and the follow-up list) is at tag `plan-v3-process-final`: `git show plan-v3-process-final:PLAN.md`.

## Stage

**S1 (semantic slice) is open; S0 is not closed** (S0-ROOT-05's principal session (U) and S0-ROOT-06 are pending). Later stages (S2 breadth and instruments, S3 causal pilot, S4 confirmatory ML, S5+) are in the stage table at the tag and in `NORTH_STAR.md`.

**S1 close** (user decision 2026-09-28): the browser demo end to end, the battery (M3), the U step (the user clicks approve in the browser), and the user's decisions on the Fast model and the résumé wording.

## Milestones

- **M1:** one live, infra-clean `x-out-of-envelope-approval` run that ends VERIFIED_COMPLETE and passes `make evidence-check RUN=<dir> MODE=claim`.
- **M2:** each of the 4 S1 families (`cp-direct-discount`, `cp-hidden-fee-readback`, `x-out-of-envelope-approval`, `x-user-mind-change`) has at least one such run.
- **M3:** the battery: 10 runs per family, success rate reported with infra ends separate (ADR-0023 tiers).

Status: **M1 not reached.** 0 of the local live bundles has ended `completed`.

## Trajectory ledger: `x-out-of-envelope-approval`

From `tasks/families/x-out-of-envelope-approval.yaml`: envelope $65/24 mo/$0 fees; unstated approval limit $72; ladder save-1 $78 → save-2 $69; levers tenure 8 years, Orbit Mobile $62.

| # | Step | Furthest clean run that reached it |
|---|---|---|
| 1 | Disclosure and identity (name, last4 recorded and voiced) | reached; but #7 (2fd267) and #9 (358c99) abandoned here: Slow never recorded the user's name/last4 |
| 2 | Ask for a discount | reached |
| 3 | save-1 $78 recorded and read back | #4 (ddc68c), #5 (266e2b) |
| 4 | Ask the user for tenure; the fact goes public | #8 (6235ab) asked; recorded private (phrasing miss, fixed on `task/s1-sys-98`) |
| 5 | Use the tenure or competitor lever | not reached |
| 6 | save-2 $69 recorded and read back | not reached |
| 7 | `request_approval` for save-2 (outside the $65 envelope, inside $72) | #5 requested approval for save-1 instead; the sim approver denied ($78 > $72) |
| 8 | Approved; accept released and heard | not reached |
| 9 | Confirmation number; `check_account` | not reached |
| 10 | VERIFIED_COMPLETE | not reached |

Smokes #4–#9 (2026-09-29, Slow = Gemini 3.8 Flash via OpenRouter, Fast = Luna effort none): Slow effort low gave no reasoning and poor judgement; medium was best (first approval request); high was truncated by Slow's 1,500 max_tokens, fixed by #301 (8,192 runaway guard). After #298/#301 the blocker is Slow's judgement (unrecorded identity, unused tenure), not mechanism.

## Now / Next

1. **Waiting on the user:** the Slow model and effort (see below). Until then, smokes run Slow effort medium on Gemini 3.8 Flash.
2. Land `task/s1-sys-98` (tenure goes public in the phrasings users use; 39 lines, `slow/tools.py`): step 4.
3. Offline scripted-Slow walk of the whole ladder (extend the SlowScript in `tests/support/web_demo.py` from save-1 + direct approval to tenure → save-2 → approval → accept → confirmation → `check_account`). Passing it shows the mechanism works and the block is Slow's judgement; failing it finds a mechanism bug offline.
4. One "heard" rule: move the GUIDE/ask-heard decision into one pure function in `guard/` and delete the copies in `obs/guides.py` and `obs/grading.py` (obs may import guard); acceptance: `diagnose` output byte-identical on the local `runs/` bundles.
5. Then fix the step the latest clean runs stop at, 3 live runs per change.

## Waiting on the user

- **Slow model and effort** (a product role, so the user decides): Gemini 3.8 Flash's judgement failures dominate the last runs. OpenRouter candidates and prices per M tokens in/out, as listed on 2026-09-29: claude-sonnet-5.5 2/10, gpt-6-sol 2/10, claude-haiku-4.5 1/5, deepseek-v4-pro 0.96/1.91, gemini-3.8-flash 0.75/3.75. Options: keep Gemini at effort medium; or a one-off diagnostic arm with a stronger Slow on the same family (≤ 3 runs) before deciding.
- The S0 principal session and the S1 U step (in person).
- Root-run G steps parked until M1: `make pull-through MODE=full` for S1-CON-01/05/08.

## Frozen until M1

- New product-lane features (web, API, obs) beyond fixes on the session path; new obs detectors and lexicon growth.
- S2 (including follow-ups to S2-SYS-02, the Ear-audit core).
- Model side: SFT data generation and distillation, model-selection studies, same-state probes (S1-MOD-08), Opus label rewriting. The pre-registered profile re-test (S1-MOD-10) is done: the `pl_cp_v4`/`pl_user_v2` live flip is blocked as pre-registered.
- Temporal/Postgres and other durability work.

## Standing decisions (still in force)

- Fast in development: OpenRouter `openai/gpt-6-luna`, `reasoning_effort` none; Qwen enters only after fine-tuning (user, 2026-09-28).
- Slow and world default to Gemini 3.8 Flash via OpenRouter (#297); world stays Gemini by the family rule (user, 2026-09-29); teacher = DeepSeek (user, 2026-09-29).
- Live profiles `pl_cp_v3` / `pl_user_v1` (`kernel/lanes.py`); `semantics-v1` is not frozen yet (S3).
- Training labels: hosted-model outputs may be SFT labels and Opus-rewritten text is allowed, with provenance; such adapters are not published (ADR-0022 and amendment).
- Outcome tiers A–F, X, S and F-infra (ADR-0023); infra ends are reported apart from agent outcomes.
- TeamRouter: not topped up; a run failing on the balance is F-infra (user, 2026-09-28). The headroom probe runs in S3, not S1.
- Merge authority: the session squash-merges after CI and its tier's review; stage closes, contract changes after `semantics-v1`, publishing, the split draw, the unseal and destructive steps need the user.
