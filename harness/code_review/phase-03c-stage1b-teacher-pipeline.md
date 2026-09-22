# Phase 03C Stage 1b Teacher Pipeline Review

**Target**: `feat/phase-03c-stage1b-teacher-pipeline` working tree against
`main` at `027bc81`, reviewed before any hosted call.
**Reviewer**: independent read-only `reviewer` subagent (Claude Opus, high
effort, fresh context).
**Final recommendation**: Approve to run the pilot (conditions applied).

## Scope reviewed

Credential and spend safety (key never persisted; `max_retries=0`, 60 s
timeout; pre-call worst-case budget; shared ledger; `--dry-run` makes no
client); prompt parity between teacher, training record, and
`Phase03CQwenAdapter.build_prompt`; filter semantics vs
`evaluate_fast_result_v3`; injectivity of the (act, needed) → oracle action
inverse used by F3; pilot selection determinism and decision rule; manifest
reproducibility and tamper detection; scope (frozen files, deps, ignore
rules); real-run failure modes.

## Findings and resolutions

- Important 1 — curation artifacts overwritten between models → model-prefixed
  file names; `--check` validates per model.
- Important 2 — F2 ignored `reason_code` while the evaluator compares the
  full `reasoner_request` → acceptance uses full equality; the contract's
  literal act+needed rate is reported separately and drives Go/Stop.
- Important 3 — Stop rule used the F1-conditional rate → unconditional
  total-sample F2 as the contract states; recorded in the preflight.
- Minor 4–8 — prompt-fingerprint assertion in curation (`prompt_drift`),
  resume tops partial prompts up to k, report stores selection parameters,
  docstring/preflight text fixes, ledger accounting note.
- Real-run mitigations — `finish_reason` recorded; missing usage keeps the
  content and charges worst case; transport smoke in a separate out-dir
  before the 200-prompt run (executed; it exposed the v3 convention gap and
  the Gemini fence behaviour and led to prompt v4).

## Verification observed by the reviewer

New test modules passed; prompt-set check consistent; `--dry-run` worst
case USD 9.87 (later 10.74 with v4) ≤ 15; frozen-file diff empty; no
dependency changes.
