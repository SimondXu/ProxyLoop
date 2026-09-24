# Docs: contract-semantics limits (A-3, A-5, A-9, R-11 (a), R-13 (c))

Bounded P2 change from `harness/context/audit-remediation-status.md` §4 and
the backlog list. Branch `docs/contract-semantics-limits` from `origin/main`
@ `74e2073`. The root orchestrator adopted the options below; this change
records them as documentation plus characterization tests. No product
behaviour change.

## Items

- **A-3** (`harness/code_review/repo-audit-A.md` §A-3): the capability
  manifest is the only vocabulary the executor will execute; the executor
  alone binds an `ActionIntent` to a manifest capability. Contract validation
  does not. Rewrite `docs/architecture.md` (Model Collaboration and Routing,
  Safety invariants) and add a dated amendment to
  `docs/decisions/2026-08-23-fast-slow-orchestration.md`. Assert
  `capability_action_mismatch` in the executor denial table (audit B1 N1;
  `unsupported_capability` is already asserted there since the approval-ledger
  fix).
- **A-5** (§A-5): define `Evidence.content_hash` as the SHA-256 of the
  canonical bytes of the artifact named by `(source_type, source_ref)`, with a
  per-source-type referent table. `CONTEXT.md` Evidence entry,
  `docs/architecture.md`, and a code comment (not a docstring) above
  `Evidence`. Characterize with a completed runtime Case.
- **A-9** (§A-9): list the ephemeral contract types whose `revision` is
  always 1; consumers must not compare it. `docs/architecture.md` and the
  `CONTEXT.md` Entity Revision entry; remove the architecture claim that every
  revision-carrying contract has an Entity Revision.
- **R-11 option (a)**: `CONTEXT.md` Material Terms becomes the implemented
  definition; fees/credits bound only in aggregate; approval binds neither the
  fee breakdown nor applied changes. Update `negotiation_catalog.py`
  (`BoundTerms` docstring only) and `docs/architecture.md`.
- **R-13 option (c)**: record unbounded `model_traces` retention and the
  planned append-only trace log (`storage_version` 3, with R-12) in
  `docs/architecture.md`.

## Out of scope

- Any contract, schema, runtime, or storage change (A-3's `ActionIntent`
  capability reference, A-5's `artifact_kind`, removing `revision`, binding
  fees or applied changes, the trace log itself).
- `ml/`, `data/`, frozen modules, other `CONTEXT.md` entries.

## Acceptance

1. Every changed statement is checked against code and cited with file:line
   in `harness/log/docs-contract-semantics-limits.md`, with each `CONTEXT.md`
   before/after sentence.
2. `make contracts-check` reports no generated contract change.
3. New tests pass; `make format-check lint typecheck`, `make preflight-fast`,
   and `make test` pass.
