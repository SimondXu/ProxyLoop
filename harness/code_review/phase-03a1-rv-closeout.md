# Phase 03A1-R/V Closeout Review

**Date**: 2026-08-24
**Reviewer**: independent Terra reviewer
**Decision**: Approve
**Unresolved Critical findings**: None
**Unresolved Important findings**: None

## Scope reviewed

- Phase 03A1-R canonical hosted rerun evidence and Phase 03A1-V validity-smoke
  evidence.
- The offline R5 checker remediation and its refingerprinted-tamper coverage.
- Preservation of the canonical R4/R5 artifacts and the Phase 03A1-R/V scope
  boundary.

## Remediation verified

The R5 checker now typed-validates the embedded `EvaluationSummaryV2` and
independently recomputes or binds:

- `model_call_count`;
- hosted maximum cost, actual cost, and cost-accounting completeness;
- failure slices;
- model and prompt provenance;
- selected episodes, references, baseline metrics, smoke metrics, and fixed
  provider/model/reasoning metadata.

The report's cost and metric disclosure text is frozen. Focused tests reject
refingerprinted tampering of headline metrics, selected episodes, references,
summary cost, model-call count, disclosure text, failure slices, model
provenance, and the nested R4 evidence.

## Terra verification

Terra actually ran and passed:

- 47 Phase R/V, adapter, and schema focused tests;
- `make hosted-rerun-source-check`;
- `make hosted-rerun-check`;
- `make validity-smoke-check`.

Terra made no Provider/API call, generator/model call, Git operation, or
`.env` read.

## Root authoritative gate

The complete `make preflight` was run by root and exited 0. Its authoritative
result was 138 runtime tests passed and 115 ML tests passed, with all format,
lint, strict mypy, contract, TypeScript, artifact, layout, uv-lock, offline
pnpm, `compileall`, Docker Compose, and diff checks passing. This is recorded
as root execution evidence, not as a Terra observation.

## Artifact and boundary evidence

- Canonical R4 SHA-256:
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`.
- Canonical R5 SHA-256:
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`.
- R4 and R5 bytes remain unchanged.
- No PR, CI, GitGuardian, commit, push, or merge completion is asserted by
  this review.
- Training, PostgreSQL, Temporal, real tools/Providers, deployment, and UI
  remain outside this closeout and inactive.
