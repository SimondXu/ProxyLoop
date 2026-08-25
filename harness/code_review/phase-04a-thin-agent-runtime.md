# Phase 04A Thin Agent Runtime Independent Review

**Date**: 2026-08-24
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope Reviewed

- the Phase 04A local FastAPI boundary and replaceable in-memory Case store;
- typed Router -> Slow/Fast orchestration and version-pinned Case state;
- deterministic policy, current version-bound approval, fictional-Provider
  execution, Evidence, completion verification, and at-most-once behavior;
- the multi-turn integration path, policy-parity checks, phase contract, and
  repository scope boundary;
- preservation of the immutable Phase 03A1-R/V evidence boundary.

No real Provider, external tool, deployment, channel, voice, UI, database, or
workflow service was in scope.

## Initial Review

Terra's first independent review returned **Request Changes** with two Critical,
four Important, and one Minor finding. The initial result was not an approval.

### Findings and resolutions

| Severity | Finding | Resolution recorded before rereview |
|---|---|---|
| Critical | Repository CAS after Provider side effect caused divergence | Persisted the execution claim with Case source pins, intent, approval, and proposal before Provider commit; deterministic executor idempotency and final CAS reconciliation now protect the Provider boundary, including injected CAS coverage. |
| Critical | Production fixed historical clock allowed expired approval execution | Added an injected UTC clock, monotonic event-time checks, and expiry coverage instead of relying on a frozen historical timestamp. |
| Important | Fast/Slow adapters were not injected | Made Fast and Slow adapters explicit constructor-injected typed seams, with focused adapter-injection coverage. |
| Important | `agent_core` had an undeclared dynamic telecom dependency | Kept `agent_core` contracts-only by using an explicit neutral policy protocol seam; telecom policy types remain outside the package. |
| Important | Unbounded `predefined_promotion_credit` bypass | Restricted credits to the explicitly catalogued fictional promotion token and required exact fee/total consistency; unknown credit-like changes cannot bypass policy. |
| Important | Missing Phase 04A build-log evidence | Added the implementation, remediation, final preflight, and review outcomes to the append-only build log and created this durable review artifact. |
| Minor | Provider/oracle current input mismatch was masked by the parity test | Added one shared telecom offer-compliance policy and shared public fixture inputs for Provider verification, oracle evaluation, and parity/adversarial tests. |

## Remediation and Rereview

- The implementation remediation was completed before the second review.
- The second review included an additional execution-claim CAS injection check
  to exercise stale or replayed execution claims at the Case version boundary.
- Terra's focused second-review run passed 67 tests.
- Terra also confirmed the final repository evidence: `make preflight` passed
  with Runtime 162 and ML 115 tests; contracts, artifacts, layout, locks,
  frozen offline pnpm, and Compose checks passed.
- Canonical r4 SHA-256 remains
  `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`.
- Canonical r5 SHA-256 remains
  `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`.
- No `ml/` or historical Phase 03A1 artifact diff was observed.

Terra's final independent decision is **Approve** with no unresolved blocking
finding for the bounded Phase 04A implementation.

## Verification and Boundaries

- The review was read-only and did not commit, push, publish, or alter Git
  history.
- No model or external API call was made, and no credential was read.
- Additional model evaluation, r6/r7 work, training, PostgreSQL, Temporal,
  real tools or Providers, authentication, external channels, voice, UI,
  deployment, and release remain outside this gate.
- Phase 04A is complete and independently approved. No subsequent
  implementation phase is activated; Phase 03B and all other out-of-scope
  work require a new explicit gate.
