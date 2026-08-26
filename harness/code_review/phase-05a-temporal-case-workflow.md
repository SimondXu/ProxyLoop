# Phase 05A Temporal CaseWorkflow Independent Review

**Date**: 2026-08-26
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- inward Case Runtime ownership and API compatibility re-exports;
- strict Workflow input, command, transition-reference, and idempotency
  contracts;
- PostgreSQL authority, command receipts, canonical approval expiry, and
  terminal-state behavior;
- Temporal Update-with-Start/Update dispatch, retry taxonomy, durable timers,
  worker recovery, replay, time skipping, and Continue-As-New;
- API failure-category redaction, explicit Temporal readiness, direct-mode
  compatibility, and the complete Phase 05A diff and fault matrix.

The reviewer was read-only and made no Provider/model call, external effect,
file edit, commit, push, or merge.

## Findings and remediation

The initial review returned **Request Changes** with two Important findings.
Two focused rereviews then sharpened the remaining timer-race proof before the
final approval.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Important | Known non-retryable `state_invalid` and `model_path` failures fell through to a generic Temporal-unavailable HTTP category. | The API now maps each known category to its own stable redacted response and tests both paths; only unknown transport failures become `temporal_unavailable`. |
| Important | Real Temporal evidence did not yet prove pending-approval Continue-As-New expiry or a timer/update race. | The time-skipping expiry test now crosses an explicit run-ID change before the canonical PostgreSQL expiry transition. |
| Important refinement | The first race test sent approval after advancing past expiry, so it was serial. | The test was changed to submit approval before expiry and wait for Temporal Update acceptance. |
| Important refinement | Update `ACCEPTED` alone could still allow a fast approval to finish before the clock moved. | A test-only approval Activity gate now proves the handler holds the Workflow command lock while the clock crosses expiry; releasing the gate yields one approved transition and no stale expiry. |

## Final rereview

The final rereview returned **Approve** with no unresolved Blocking, Important,
or Minor finding. It confirmed that the gated race excludes both a prefinished
approval and a prefinished timer: the approval Activity is observably in
flight, its Update result remains incomplete while test time crosses the exact
deadline, and the timer must wait on the same Workflow lock. After release,
PostgreSQL contains one execution, the expected execution/confirmation
Evidence, no `approval_expired` event, and exactly three Case transitions.

The reviewer separately passed `git diff --check`. Root Sol ran the reported
real PostgreSQL/Temporal suite and owns all final test, preflight, integration,
and completion claims.

## Authority and scope conclusion

The approved slice durably orchestrates only the deterministic fictional
Provider. PostgreSQL remains the sole business truth source; Policy, Approval,
Executor, Evidence, and Verifier authority is unchanged. The review does not
authorize real Providers/tools/channels, real model calls or credentials,
outbox/reconciliation, authentication, production UI, deployment, release,
training/evaluation/playbook work, wire-contract redesign, production
exactly-once, multi-tenancy, or capacity claims. Phase 06 remains unauthorized.
