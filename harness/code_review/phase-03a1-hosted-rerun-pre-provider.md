# Phase 03A1-R Pre-Provider Independent Review

Date: 2026-08-24

Reviewer: Terra (`phase03a1_r_pre_provider_review`), read-only

Final decision: **Approve**. No unresolved Critical or Important finding.

## Review Boundary

- Reviewed the complete Phase 03A1-R pre-Provider working-tree change.
- Did not read credentials or call the Provider/API.
- Assessed immutable r2/r3 binding, probe-to-matrix authorization, cost and
  dispatch accounting, error-evidence safety/completeness, offline replay and
  tamper detection, and prohibited Phase 03B/product scope.

## Review History

1. Initial Request Changes: a response with usage but no response ID could fail
   before its terminal evidence was serialized; arbitrary Provider messages
   could persist echoed request/secret data; and pre-dispatch validation lacked
   a source-only gate independent of r4.
2. Second Request Changes: one mutable `last_error` per adapter allowed a later
   matrix success to overwrite an earlier known-cost failure.
3. Third Request Changes: the offline checker did not reconcile every failed
   hosted call with exactly one error-history row, so refingerprinted removal,
   index tampering, or duplication could pass.

## Accepted Remediation

- Missing response IDs retain usage and usage-accounted cost, produce
  `failed_invalid_response` plus `MissingResponseId`, and block later probes.
- Arbitrary Provider messages were removed from persisted error schemas. Only
  class, HTTP status, request ID, Provider code/type/parameter, scope, and
  1-based call index remain.
- Adapter errors accumulate in an immutable-view per-call history and are not
  erased by later successes.
- The artifact checker derives dispatched failures from probe and matrix call
  evidence, requires exact `(scope, call_index)` coverage, rejects orphan and
  duplicate rows, and reconciles probe-embedded errors with the global history.
- Refingerprinted deletion, wrong-index, and duplicate tamper regressions fail.
- `hosted-rerun-source-check` validates deterministic pre-dispatch inputs
  without requiring the not-yet-created r4 artifact.
- The execution-contract fingerprint blocks adapter/evaluator/runner/Qwen/lock
  or command drift between probe and matrix.

## Independent Verification

- 24 focused adapter/rerun tests passed.
- Focused Ruff, strict mypy over three source files, source-only check, and
  `git diff --check` passed.
- No Provider/API call was made and no credential was read.

The r4 artifact, complete repository preflight, hosted probe, and hosted matrix
remain intentionally unrun at this pre-Provider gate.
