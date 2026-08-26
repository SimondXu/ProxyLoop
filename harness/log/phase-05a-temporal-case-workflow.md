# Phase 05A Temporal CaseWorkflow Execution Log

**Date**: 2026-08-26
**Baseline**: synchronized `main` at `95ac99c`
**Branch**: `codex/phase-05a-temporal-case-workflow`
**Status**: Bounded product phase complete and returned to idle. Phase 06 is
unauthorized. PR/hosted integration remains pending at the time of this
pre-merge log.

## Delivered

- Extracted the Case application Runtime and memory/PostgreSQL repositories
  into the inward `proxyloop_case_runtime` package while retaining compatible
  API re-exports and unchanged default direct-memory behavior.
- Added strict versioned Case workflow/command/transition-reference contracts,
  PostgreSQL command receipts, and the canonical persisted approval-expiry
  transition.
- Added the scripted/PostgreSQL Temporal worker, activity adapter, client,
  configuration, readiness, Update-with-Start/Update API dispatch, retries,
  durable approval wait, worker recovery, and Continue-As-New.
- Added guarded real PostgreSQL and Temporal fault-injection coverage for
  duplicate callbacks, pre/post-commit failures, retry exhaustion, queued and
  restarted workers, replay, time skipping, Continue-As-New, cross-run
  deduplication, and the approval/timer lock race.
- Kept PostgreSQL as the sole Case/approval/Evidence/completion truth source
  and preserved deterministic Policy, Approval, Executor, Evidence, and
  Verifier authority.

## Local evidence

- Real disposable PostgreSQL plus Temporal integration: 9 passed in the final
  workflow file, including replay, time skipping, worker recovery,
  Continue-As-New, duplicate callback/receipt, retry faults, API projection,
  canonical expiry, and the gated approval/timer race.
- Real disposable PostgreSQL Runtime regression: 29 passed across Phase 04C
  persistence and the extracted Phase 05A Case Runtime.
- Direct/API compatibility regression: 52 passed with 2 guarded PostgreSQL
  tests skipped when the database variable was absent.
- Affected Ruff formatting/lint, strict mypy, layout, and diff checks passed.
- Independent Terra review: final Approve with no unresolved Blocking,
  Important, or Minor finding after two initial Important findings and two
  race-proof refinements were remediated and rereviewed.

## Final gate evidence

- Final real-dependency `make phase05a-check`: 22 passed in 26.50 seconds
  against the disposable `proxyloop_test` PostgreSQL database and local
  Temporal service.
- Final stable-diff `make preflight`: passed once. Runtime reported 245 passed
  and 31 infrastructure-dependent skips; the separate real-dependency gate
  passed all 22 Phase 05A tests. ML reported 177 passed. Web lint, typecheck,
  29 tests, and production build passed. Contract/artifact drift checks, Ruff,
  strict mypy, both uv locks, frozen offline pnpm, Harness layout, script
  compilation, diff checks, and Compose configuration also completed with an
  exit-zero result.

## Hosted and integration evidence

- The bounded PR must pass fresh hosted `phase-gate` and GitGuardian checks
  before squash merge. The PR check run and merge record are authoritative for
  that later integration evidence.
- Only the fully merged short branch may be cleaned after confirming a clean
  worktree, pushed head, merged PR, and no unique unpushed work.

## Stop boundary

No real Provider/tool/channel, model call/credential, external-effect outbox or
reconciliation, auth, voice, production UI, deployment, release,
training/evaluation/playbook work, canonical wire redesign, production
exactly-once, multi-tenant, or capacity claim is authorized. Phase 06 remains a
separate user gate.
