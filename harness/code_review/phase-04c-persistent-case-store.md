# Phase 04C Persistent Case Store Independent Review

**Date**: 2026-08-25
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- the strict versioned PostgreSQL Case aggregate and row/payload revision
  binding;
- create/get/revision-CAS behavior across repository and Runtime instances;
- fictional Provider reconstruction at offered, approval, pending execution,
  rejection, and verified terminal states;
- restart, recovery, terminal-repeat, complete Evidence, and exact execution
  metadata semantics;
- storage configuration, stable redacted failures, disposable local database,
  hosted CI wiring, dependency lock, and architecture/runtime documentation;
- the complete bounded Phase 04C working-tree diff against its executable
  contract.

The review was read-only. It made no external model or Provider call, used no
credential or ordinary developer database, and performed no Git publication.

## Initial review and remediation

Terra initially returned **Request Changes** with three Important findings.

| Severity | Finding | Resolution |
|---|---|---|
| Important | Terminal reconstruction verified confirmation Evidence but accepted deleted or altered simulator-transition Evidence. | Terminal decode now requires exactly one field-for-field deterministic simulator-transition Evidence; deletion and six field-tamper cases fail closed. |
| Important | A pending row could carry a nonzero execution count, and non-executing states could carry execution metadata, creating impossible or unrecoverable Runtime states. | Offered, waiting, rejected, pending, and terminal states now enforce a complete execution-count and metadata matrix. |
| Important | Raw psycopg or validation causes could render in an unhandled startup traceback even when the public error string was stable. | PostgreSQL public boundaries suppress internal causes; `server.main()` converts construction failures to stable CLI stderr and never starts Uvicorn. |

Focused remediation tests passed against disposable PostgreSQL, and Sol's
combined Phase 04A/04B/04C regression passed with 67 tests.

## Final rereview

The first rereview confirmed all three Important findings closed and found one
Minor integrity omission: terminal execution pins used a hand-written field
comparison that omitted `planning_basis_fingerprint`.

The comparison was replaced with complete `ModelInputPins` value equality and
a real PostgreSQL single-field tamper regression. The focused PostgreSQL gate
then passed 22 tests; affected Ruff, strict mypy, and diff checks passed.

Terra's final recommendation is **Approve**. It found no unresolved Critical,
Important, or Minor defect, no `CaseRepository` or HTTP contract change, and no
scope drift. Final repository preflight, hosted CI, GitGuardian, PR, merge, and
branch cleanup remained intentionally outside the review evidence at approval
time.

## Authority and scope conclusion

The approved behavior is restart-safe only for the deterministic fictional
Provider. PostgreSQL owns aggregate persistence and cross-process revision
CAS; deterministic policy, Evidence validation, and the canonical completion
verifier retain authority. This review does not claim exactly-once real
external effects, production migrations, Temporal durability, real Providers,
model promotion, deployment, or release.
