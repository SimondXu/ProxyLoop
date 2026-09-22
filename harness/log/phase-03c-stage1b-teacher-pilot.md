# Phase 03C Stage 1b Teacher Pipeline and Pilot Execution Log

**Date**: 2026-09-21
**Baseline**: integrated `main` at `027bc81` (Stage 1a)
**Branch**: `feat/phase-03c-stage1b-teacher-pipeline`
**Contract**: `harness/build/phase-03c-fast-model-distillation.md`, Stage 1
(teacher adapters, rejection-sampling pipeline, pilot gate)
**Status**: pilot complete with decision **Go** (claude-sonnet-5) / **Stop**
(gemini-3.5-flash); independently reviewed code; status returned to `idle`.
Full generation (Stage 1c) is the next bounded change.

## Delivered

- `relay_teacher.py`: `RelayTeacherAdapter` on the OpenAI-compatible relay
  seam (configurable model, v4 prompt byte-identical to
  `Phase03CQwenAdapter.build_prompt`, temperature 0.7, `json_object`,
  `max_retries=0`, 60 s timeout, sanitized errors, `finish_reason` and
  `usage_missing` recorded), shared `TeacherLedger` with pre-call worst-case
  budget enforcement and `ml/configs/teacher-rates.json` (placeholder
  upper-bound rates; every USD figure is an accounted estimate).
- `phase03c_prompt_set.py` + `scripts/build_phase03c_prompt_set.py`:
  parameterised snapshots/views for both positions, 4,000 train + 400 dev
  rows, manifest with fingerprints only (`data/manifests/phase-03c-prompt-set.json`,
  compiler v4, content `0556af17…`).
- `phase03c_teacher_filters.py` + `teacher_pipeline.py` +
  `scripts/run_phase03c_teacher_pilot.py`: F1 strict JSON/schema, F2 full
  target agreement, F3 environment replay, F4 detectors (strict
  `fact_updates_present`), F5 optional, dedup ≤ 2/prompt, split guard,
  `prompt_drift` guard, resumable sampling, per-model curation artifacts,
  pilot report with Go/Stop/Hold, `--dry-run`, `--check` (recomputes from
  raw samples); Makefile `phase03c-prompt-set(-check)`,
  `phase03c-teacher-pilot-check` (in `make test`).
- Prompt **v4** (`phase-03c-fast-compiler-v4` = v3 + `DECISION_CONVENTION`
  block, additive; v3 untouched). Untuned v4 smokes:
  `arm-a-untuned-8b-v4.json` (strict 6/6, schema 6/6, act 6/6,
  reasoner_request 6/6, end-to-end 6/6, median 8.7 s, max prompt 1698
  tokens) and `arm-a-untuned-4b-v4.json` (act 3/6, end-to-end 3/6).
- Harness: preflight (with post-smoke decisions), this log, code review.

## Hosted spend (accounted estimates from the placeholder rates)

- Transport smokes and Gemini probes: ≈ USD 0.25 (scratch out-dirs).
- Pilot (`data/experiments/phase-03c/teacher/`): claude-sonnet-5 600 calls,
  1,737,144 input / 239,559 output tokens, USD 8.80; gemini-3.5-flash 600
  calls, USD 0.75; ledger total USD 9.55 ≤ 15 cap. Zero failed calls.

## Pilot result (200 prompts, 20 per train family, k = 3, prompt v4)

| teacher | F1 strict JSON | F1∧F2 (act+needed) | F1–F4 | accepted rows | decision |
|---|---|---|---|---|---|
| claude-sonnet-5 | 97.2% | 77.8% | 67.7% | 273 (of 200 prompts) | **Go** |
| gemini-3.5-flash | 0.7% | 0.7% | 0.7% | 4 | **Stop** |

Sonnet per family (F2 act+needed): absent-evidence 0.90, add-on-removal
1.00, clarification 1.00, direct-success 1.00, disclosure-restriction 1.00,
expired-approval 1.00, **fee-total-cost-trap 0.02**, **forbidden-term
0.00**, forged-evidence 0.87, multi-hazard 1.00. Quarantine reasons:
dedup cap 133, `detectors:disclosure` 59, `reasoner_needed` 73,
`dialogue_act` 43, invalid JSON 17.

Findings that Stage 1c must carry:
1. **Teacher arithmetic failure on the fee trap**: Sonnet writes the right
   numbers and the wrong comparison ("$1,127 is under the $816 cap") in
   59/60 samples — the exact hazard the deterministic policy exists for.
2. **Forbidden-term convention gap**: act is right (`counter`) but the
   teacher sets `needed: true` / `provider_state_requires_replan`; the v4
   block's rule 7 is not explicit that offer non-compliance is never a
   replan.
3. **Disclosure detector removes the family**: correct refusals name the
   requested field (`account_pin`) and the frozen 03B detector flags the
   token itself, so disclosure-restriction yields 1 accepted row. The same
   detector scores Stage 3, so training and evaluation stay consistent; the
   teacher must be told not to echo the requested field name.
   Net: accepted rows cover 7 of 10 train families. Decision recorded for
   Stage 1c: iterate the prompt to v5 (rules 7 and disclosure wording, an
   explicit total-vs-target statement), re-pilot the affected families
   within the pilot cap, add sampling concurrency, and run full generation
   at k = 2 (dedup already removed 133/600 duplicates at k = 3; k = 2 keeps
   the run inside USD 150 at the observed USD 0.0147 per call).
4. Gemini ids on this relay ignore `response_format` and return fenced or
   interleaved text; not a usable teacher under the contract's F1 rule.

## Checks

Passed (final tree): `make preflight` exit 0 — ruff/mypy, runtime 303 / 33
skipped, ML 279, web 47, all artifact checks incl. `phase03c-smoke-check`
(v3 + v4 results), `phase03c-invariants-check`, `phase03c-prompt-set-check`,
`phase03c-teacher-pilot-check` (report recomputed from raw samples);
`git diff --check`. Frozen files unchanged (reviewer verified).
Not run: Compose-profile gates. MLX token fit for v4: max 1698/2048 (8B),
1694 (4B).

## Independent review

`reviewer` (Opus, high): "Approve to run the pilot" on the code, with
Important 1–3 and Minor 4–8 applied before the pilot (model-prefixed
curation artifacts; F2 = full `reasoner_request` for acceptance while the
Go/Stop thresholds use the contract's literal act+needed F2; unconditional
Stop rule; prompt-fingerprint assertion; resume top-up; report stores
selection parameters; docs; ledger accounting note; `finish_reason` and
usage-missing handling). Reviewer's pre-run mitigation (≤ 20-call transport
smoke in a separate out-dir) was executed and drove the v4 prompt decision.
The pilot numbers above were not re-reviewed; they are recorded evidence for
the Stage 1c gate.
