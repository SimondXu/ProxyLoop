# Phase 03C Stage 1c Full Teacher Generation Execution Log

**Date**: 2026-09-21 → 2026-09-22
**Baseline**: integrated `main` at `5648ab4` (Stage 1b)
**Branch**: `feat/phase-03c-stage1c-full-generation`
**Contract**: `harness/build/phase-03c-fast-model-distillation.md`, Stage 1
(full generation, ≤ USD 150)
**Status**: complete; `training_ready = true`; independently reviewed
(Request Changes → remediation → Approve with the Stage 2 files split out);
status returned to `idle`. Stage 2 is the next bounded change and needs a
CUDA box (see the Stage 2 preflight once opened).

## Delivered

- Prompt **v5** (rule 6 comparison sentence, rule 7 "never a replan",
  no echo of the requested disclosure field) and **v6** (precedence
  sentence; rule-7 tail clause) — both additive; v3/v4/v5 bytes pinned by
  tests; committed v4 pilot and v5 re-pilot checks read their stored
  versions. Stage 1b/1c default = v6; prompt-set manifest regenerated
  (compiler v6).
- Concurrent sampling (`--concurrency`, thread pool per prompt, atomic
  worst-case reservation in the shared ledger), hard-error circuit breaker
  (401/403 or 5 consecutive failures → `stop_reason`, remaining prompts not
  charged), `--reset-failed-charges` (rebuild the ledger from raw samples:
  succeeded calls at actual cost, failed at zero), resumable top-up to k,
  `--families` targeted pilots, `scripts/run_phase03c_teacher_generation.py`
  with a self-describing generation report (`prompts_complete`,
  `run_complete`, `stop_reason`), `phase03c-teacher-generation-check` in
  `make test`. Atomic JSON writes. 319 ML tests.
- Artifacts (committed unless noted): `teacher-v5-repilot/`,
  `teacher-v6-repilot/`, `teacher-full/` (v5 outage evidence),
  `teacher-full-v6/` (final; raw samples ~15 MB and accepted JSONL
  git-ignored; manifest 3.8 MB, quarantine, quality report, ledger,
  generation report committed).

## Runs and spend (accounted estimates at the placeholder rates)

| run | prompt | calls | failed | est. USD | outcome |
|---|---|---|---|---|---|
| v5 targeted re-pilot (5 families) | v5 | 300 | 0 | 4.50 | F1 98%, F1∧F2 94%, F1–F4 91% → Go; fee-trap 1.00, forbidden-term 1.00 |
| v5 full run (aborted) | v5 | 8,000 | 7,943 | 125.84 (real ≈ 0.95) | relay 403 `pre_consume_token_quota_failed` then a 2-minute 401 storm; 57 usable samples showed a v5 regression on (counter, needed=true) families |
| v6 targeted re-pilot (6 families) | v6 | 360 | 0 | 5.43 | F1 97.5%, F1∧F2 87.8%, F1–F4 87.2% → Go; absent-evidence 0.95, disclosure 0.53 (position-2 regression, recorded) |
| v6 full run | v6 | 8,003 | 4 | 121.59 | see below; three relay keys rotated on quota (breaker fired cleanly each time) |

Stage 1c total ≈ USD 132 accounted (the aborted v5 run's phantom charge
excluded); real relay usage across all Stage 1b/1c runs ≈ USD 146.

## Full generation result (`teacher-full-v6/`)

- 4,000 train prompts, k = 2: **3,999 complete** (one prompt lost its
  second sample to the final quota stop; `run_complete = false`,
  `stop_reason = hard_error:PermissionDeniedError`).
- F1 strict JSON 97.5%, F1∧F2 (act + needed) 91.3%, full F2 91.3%, F1–F4
  90.3%. Zero failed calls charged beyond 4.
- **Accepted rows 7,196** (target ≥ 2,500), every train family covered:
  absent-evidence 736, add-on-removal 720, clarification 797,
  direct-success 708, disclosure-restriction 421 (skewed to position 1),
  expired-approval 795, fee-total-cost-trap 744, forbidden-term 792,
  forged-evidence 700, multi-hazard 783. `training_ready = true` with all
  four criteria derived (accepted ≥ target, ledger ≤ cap, zero cross-split
  families, zero forbidden model-input keys).

## Findings

1. Prompt wording has first-order effects on teacher/oracle agreement:
   v4→v5 fixed fee-trap and forbidden-term but broke the replan families;
   v6 fixed those and lost disclosure position 2 (`challenge` 30/30 → 6/30).
   Each iteration was caught by a targeted re-pilot before spend, except
   the v5 regression, which surfaced only in the aborted full run — the
   re-pilot must cover every family whose target shares the changed rule.
2. Relay keys are pre-paid; quota exhaustion presents as 403 then 401.
   Worst-case charging of failed calls turns an outage into a phantom
   ledger; the breaker plus `--reset-failed-charges` are the answer.
3. 51/614 rendered train+dev rows exceed 2,048 tokens with the 8B tokenizer
   (max 2,155); Stage 2 must set `max_length` 2,304 or drop them (decision
   recorded in the Stage 2 preflight).

## Checks

Passed (final tree): `make preflight` exit 0 — ruff/mypy, runtime 303 / 33
skipped, ML 319 (includes the not-yet-committed Stage 2 test modules that
were present in the tree), web 47, all artifact checks incl. the pilot, v5
re-pilot, and generation report checks (recomputed from raw samples);
`git diff --check`. Frozen files unchanged; no dependency changes.
Not run: Compose gates; MLX token fit for v6 (max +177 chars vs v5).

## Independent review

`reviewer` (Opus, high). Pass 1: Request Changes — Blocking: v5 regression
on (counter, needed=true) families not covered by the re-pilot; Important:
no hard-error breaker, no ledger reset procedure; Minor: report
completeness fields, atomic writes, ceiling default, preflight attribution.
All applied (v6 + re-pilot, breaker, reset, minors). Pass 2: Approve on the
code; the only remaining item was scope — Stage 2 files (MLX pipeline,
cloud package) had appeared in the tree and were split out of this PR into
the Stage 2 change; the disclosure position-2 finding was re-labelled as a
regression per the reviewer.
