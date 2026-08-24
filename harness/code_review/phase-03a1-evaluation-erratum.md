# Phase 03A1-E Independent Review

Date: 2026-08-24

Reviewer role: independent Terra high, read-only. The reviewer made no model or
API request, did not read credentials, and did not edit the workspace.

## Initial Decision: Request Changes

The first review found one Critical and two Important defects:

- a validly refingerprinted report could claim `phase_completion_ready=true`
  while learned conditions were failed or not run;
- an unavailable or runtime-failed local Qwen could be reported as a successful
  32-call gate and incorrectly allow hosted dispatch;
- a terminal Slow Provider failure was also labeled
  `router_outcome_mismatch`, although the Router correctly emitted
  `slow_refresh` and Fast never ran.

The reviewer also required the post-dispatch correction to obey frozen decision
9 rather than silently rewriting the r2 report.

## Remediation

- Report readiness and exact blockers are now recomputed from ordered condition
  states and the scripted ceiling. Valid-refingerprint tamper regressions cover
  readiness, blockers, source identity, source evidence, and abort reasons.
- Qwen `UNAVAILABLE` is a zero-usage `not_run_model_unavailable`; a runtime
  generation error is a terminal failed condition; invalid model output remains
  a measured quality outcome.
- A terminal Provider call failure accepts the observed `slow_refresh` route and
  no longer creates a false Router failure slice.
- The original r2 report remains immutable. The corrected r3 report is produced
  only by fake-adapter offline replay of captured r2 evidence, binds the source
  fingerprint and timestamp, records source hosted calls=1, new external
  dispatches=0, offline replay conditions=4, evaluator version, and the executed
  Qwen output cap=512.
- R3 uses its actual UTC generation time rather than reusing the r2 source time.
  The checker separately verifies both timestamps and all source bindings.

## Final Decision: Approve

The final incremental review found no unresolved Critical or Important finding.
It independently passed 25 focused tests, the r3 offline checker, Ruff, strict
mypy, and `git diff --check`. The remaining note is non-blocking: the Qwen cap
was historically an implicit frozen code default in r2; r3 now makes it explicit
and checker-bound without mutating r2.

This approval covers Phase 03A1-E only. It does not approve a retry, training,
training-data expansion, Phase 03B, product services, external channels, UI, or
deployment.
