# Phase 04C Persistent Case Store Execution Log

**Date**: 2026-08-25
**Baseline**: synchronized `main` at `abe6e50`
**Branch**: `feat/phase-04c-persistent-control-plane`
**Status**: Local implementation, independent review, and final repository gate
complete; hosted gates pending.

## Delivered

- Added an explicit opt-in synchronous `PostgresCaseRepository` behind the
  unchanged three-method repository interface; memory remains the default.
- Persisted one strict versioned JSONB Case aggregate with relational revision
  binding and transactional compare-and-swap.
- Reconstructed and authenticated only the deterministic fictional Provider,
  exact execution pins, both execution Evidence records, and canonical
  completion; malformed or impossible stored state fails closed.
- Proved fresh-Runtime approval, pending-claim recovery, terminal repeat, and
  cross-instance CAS against a disposable `proxyloop_test` database.
- Added PostgreSQL 17 local/CI gates, stable redacted startup/operation errors,
  the minimum Psycopg dependency, and truthful runtime/infrastructure/
  architecture documentation.

## Local evidence

- Real PostgreSQL Phase 04C integration: 22 passed.
- Combined Phase 04A/04B/04C regression before the final pin fix: 67 passed;
  the pin fix and its new real-PostgreSQL regression passed in the 22-test
  focused gate.
- Affected Ruff and strict mypy: passed; API mypy checked 8 source files.
- Runtime lock, layout, Compose normal/profile config, and diff checks: passed.
- Independent Terra review: final Approve with no unresolved Critical,
  Important, or Minor finding.
- Final `make preflight`: passed once on the stable reviewed diff. Runtime
  reported 218 passed and 18 infrastructure-dependent skips; ML reported 177
  passed; Web lint/typecheck/build passed with 29 tests. Contract drift,
  historical artifact checks, full Ruff/strict mypy, both uv locks, frozen
  offline pnpm, layout, script compilation, diff, and Compose checks passed.
- The 18 Runtime skips are the database-dependent Phase 04C cases intentionally
  kept out of the infrastructure-independent base gate; the separate real
  PostgreSQL gate passed all 22 of them and related stable-error tests.

## Remaining gate evidence

- Hosted `phase-gate` and GitGuardian: pending PR.
- Squash merge and safe short-branch cleanup: pending hosted success.

## Stop boundary

No Temporal, real Provider or tool, real external-effect recovery, model
training/promotion, authentication, channel, voice, production UI, deployment,
release, or next phase is authorized by this log.
