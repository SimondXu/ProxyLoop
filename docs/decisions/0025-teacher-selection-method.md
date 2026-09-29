# ADR-0025: Teacher selection method (S1-MOD-10)

- **Status:** proposed
- **Date:** 2026-09-29
- **Task:** S1-MOD-10 (PR1: the instruments, no model call; PR2: the report)

## Context
The teacher is the model whose Fast turns become SFT labels and that plays Fast in teacher-in-harness episodes (TRAINING §2). The user excluded Sonnet (cost). The candidates are `glm-5.3-flash`, `gemini-3.8-flash` and `deepseek-flash`, via TeamRouter. Teacher and world must be different families, and Slow is `gemini-3.8-flash`. ADR-0022 covers using hosted outputs as labels. This ADR fixes the method before any candidate call.

## Decision
1. **Arms:** each candidate model at two effort levels (rule 3), so up to six arms, plus the recorded Luna answer as a reference arm, all blinded together. `deepseek-flash` is an alias echoing `deepseek-v4-1-flash-260910`; every row records its served echo.
2. **States:** `scripts/mod/probe_same_state.py` over the `runs/` train bundles on the current fingerprints: 127 views from 5 runs (cp 103, user 24). The funnel's drops are disclosed: 45 stale-fingerprint bundles and 73 turns without a recorded seed. Each arm gets the kernel's request (the session sampling: temperature 0.3, top_p 0.9) except `max_tokens`, which is 16384 for every candidate arm. This is a runaway guard, so the arms differ only in effort; the reference was recorded at the session's 160. Length is controlled by the prompt and measured (D7), not truncated. There is one call per view per arm and no retry (the adapter's single pre-first-token connect retry is shown). A dead endpoint raises `LLMUnavailable` and aborts the arm (rule 6). A medium call can exceed the adapter's 120 s read timeout: that arm aborts, and its partial rows are kept and disclosed (`not_run`). Each arm is a separate probe invocation. **Exception to AGENTS rule 3**, as in ADR-0024: this is a component-level, open-loop probe of single Fast calls (precedent S1-MOD-08).
3. **Effort rule (pre-registered):** the *low-end* arm uses `reasoning_effort` none; if the endpoint refuses it (HTTP 400 on the one gate call), it uses minimal, then low: the first accepted value. The *medium* arm uses medium; if that is refused, the arm is not run and the report says so (no substitute). Gate calls use the first view and are discarded, not scored. The low-end arm is the live teacher-in-harness shape (TRAINING §2.1, wall clock); the medium arm is the offline-relabel shape (§2.2), where latency does not matter. Medium is the vendor's recommended default for quality (Gemini 3 thinking docs), and published work finds that reasoning can hurt exact-format instruction following (arXiv 2505.11423, 2606.09662), so the effect is measured, not assumed. Length stops (runaways), reasoning tokens and Qwen tokens are reported per arm.
4. **Instruments, pinned before any candidate call:** the checks and scoring module `scripts/mod/teacher_select.py` sha256 `7bb2b28d09b6c12201ccff3055bc50019db3da96caf84acda277c8153529a366` and the judge rubric v1 `docs/decisions/data/teacher-select-rubric.md` sha256 `f29d7394ef9cb57d608a3cc718206e1f3c451776352e88aa1ddb234d6d68b794` (a test keeps both equal to the committed files).
   - Hard checks: D1 parse_ok, D2 guide_directive, D4 no invented numbers, D6 authority wording (a frozen phrase list with a negation/modality guard), and D7 fits the student budget (at most 160 pinned-Qwen tokens, the student's production cap).
   - Informational checks: D3 slots stated, D5 relay expected, and hold agreement with the reference (Luna, not gold).
   - Judging: T1–T6 by blind Opus subagents, instruction-isolated as in ADR-0024. Batches hold 8 views with up to 7 outputs each. Errored outputs are not judged.
   - Blinding leak: the reference's recorded speech appears in later prompts of its run. The export counts the views affected per batch (`reference_visible`); the no-call dry run found 50 of 127 views at 8 views per batch.
5. **Metrics:**
   - USEFUL (primary) = D1 ∧ D2 ∧ D4 ∧ D6 ∧ D7 ∧ T1..T6, over every row of an arm, so an error counts as not useful.
   - Also reported: judged all-pass, per-criterion rates, TTFT and latency (relay-measured; the reference's are not comparable), and cost per useful row from per-arm TeamRouter balance deltas.
   - Paired cluster bootstrap by run, for: every candidate − reference, the two arms of each model, and the models at one level.
6. **Decision:** the user decides on the data; there is no switch rule. The world then follows the family rule (teacher DeepSeek → world Gemini; teacher Gemini → world DeepSeek; GLM is expected to lose but is cheap to include). A small closed-loop T check on the chosen world comes later.

## Consequences
This is an internal instrument choice, not a claim: nothing from it goes into `docs/claims.yaml` or the README. The probe is open-loop, so it has no outcomes, no compounding errors and no timing effects. The sample is small (5 run clusters), so the CIs are wide.
