# Phase 03C Stage 1c Full Generation Review

**Target**: `feat/phase-03c-stage1c-full-generation` against `main` `5648ab4`
**Reviewer**: independent read-only `reviewer` subagent (Claude Opus, high,
fresh context), two passes.
**Final recommendation**: Approve (after remediation and the Stage 2 split).

## Findings and resolutions

- Blocking — v5 rule-7 sentence made the teacher skip rule 5 (evidence
  missing) when an offer was also non-compliant: absent-evidence
  (counter, needed=true) 27/30 → 0.05 in the aborted full run; the targeted
  v5 re-pilot had not covered those families. Resolution: prompt v6
  (precedence sentence + rule-7 tail clause), v6 re-pilot over the six
  affected families (Go; absent-evidence 0.95), full run on v6.
- Important — no hard-error breaker: 7,942 401s in two minutes, each
  charged at worst case. Resolution: breaker on 401/403 or five consecutive
  failures with `stop_reason`; verified in the v6 run (three quota stops,
  4 failed calls total).
- Important — no ledger reset procedure. Resolution:
  `--reset-failed-charges` on both scripts, documented in the script
  docstring, ledger accounting text, and the preflight.
- Minor — generation report completeness fields, atomic JSON writes,
  ceiling default 140, preflight attribution of the v5 re-pilot failures
  (direct-success: 2 act errors + 6 `finish_reason=length` truncations;
  disclosure: 10 act errors), disclosure position-2 labelled a regression.
- Scope — Stage 2 training files present in the tree were excluded from
  this PR.

## Verification observed by the reviewer

v6 == v5 + exactly two edits (programmatic diff); v3/v4/v5 constants
unchanged; committed v4 pilot check and v5 re-pilot check recompute from
raw samples; breaker test bounds attempts to 3 + workers×k with zero
reserved USD; reset keeps only succeeded calls' actual cost; frozen files
untouched; ML tests, lint, typecheck, `git diff --check` passed.
