# Phase 04D Control-Plane Operations Execution Log

**Date**: 2026-08-26
**Baseline**: synchronized `main` at `e64fa85`
**Branch**: `feat/phase-04d-control-plane-operations`
**Status**: Bounded product phase complete and returned to idle. Phase 05A is
an unauthorized gate; Temporal has not started. PR/hosted integration remains
pending at the time of this pre-merge log.

## Delivered

- Added one correlated, allowlisted, non-retaining JSON operation record per
  Case or health HTTP request with deterministic route, actual adapter/storage
  profile, policy/approval/execution/verifier outcome, stable error category,
  response status, and latency.
- Added process-only liveness and configured-storage readiness. Memory is
  immediately ready; PostgreSQL executes only `SELECT 1`; neither path reads or
  mutates a Case or dispatches a model.
- Separated `StorageUnavailableError` from malformed stored-state validation
  and added stable redacted HTTP/CLI behavior for storage, model, validation,
  stale-CAS, conflict, and internal failures.
- Proved actual injected OpenAI-compatible fake transport can write and advance
  a PostgreSQL Case before an explicit scripted Runtime reads and safely
  completes the same persisted Case, with no automatic fallback.
- Added a credential-free scripted/fake-timeout diagnostic profile that records
  p50/p95, error and timeout rates, CPU/wall time, and max RSS as local-only
  observations.

## Local evidence

- Real disposable PostgreSQL integration: 24 passed after every material review
  remediation. The gate covers readiness, strict storage behavior, stale CAS,
  pending recovery, restart/idempotency, and fake-model-to-scripted switching.
- Final focused Phase 04D suite: 16 passed.
- Final combined Phase 04A/04B/04D regression: 62 passed.
- Final local diagnostic check: 7 requests and 7 operation records; p50
  2.075 ms, p95 5.456 ms, error rate 1/7, timeout rate 1/7, CPU time
  25.699 ms, max RSS 67,272,704 bytes, and wall time 40.351 ms on the recorded
  local macOS/Python run. These values are diagnostic only and are not a
  capacity, production p95, real-model, OOM, autoscaling, or promotion claim.
- Ruff formatting/lint and strict mypy passed; mypy checked 41 Runtime and 30 ML
  source files. Staged and working-tree diff checks and Harness layout passed.
- Independent Terra review: final Approve with no unresolved Critical,
  Important, or Minor finding after one Critical and four Important findings
  were remediated and rereviewed.
- Final `make preflight`: passed once on the stable reviewed semantic diff.
  Runtime reported 234 passed and 20 infrastructure-dependent skips; the
  separate real PostgreSQL gate passed all 24 database-dependent tests. The ML
  suite, Web lint/typecheck/test/build, contracts and artifact drift checks,
  full Ruff/strict mypy, both uv locks, frozen offline pnpm, layout, script
  compilation, diff, and Compose configuration all completed successfully in
  the same exit-zero preflight.

## Hosted and integration evidence

- The bounded PR must pass fresh hosted `phase-gate` and GitGuardian checks
  before squash merge. The PR check run and merge record are authoritative for
  that later integration evidence.
- Only the fully merged short branch may be cleaned after confirming a clean
  worktree, pushed head, merged PR, and no unique unpushed work. The preserved
  unrelated legacy UI worktree/branch remains untouched.

## Stop boundary

No Temporal SDK, workflow worker, timer, signal, durable retry, real Provider or
tool, outbox/reconciliation, model training/promotion, real-model serving,
authentication, channel, voice, production UI, deployment, release, or next
phase is authorized by this log.
