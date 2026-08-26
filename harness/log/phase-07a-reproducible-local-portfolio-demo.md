# Phase 07A Reproducible Local Portfolio Demo Execution Log

**Date**: 2026-08-26
**Baseline**: integrated `main` at `17f6585`
**Branch**: `codex/phase-07a-reproducible-local-portfolio-demo`
**Status**: Bounded Phase 07A complete and returned to idle. PR/hosted
integration remains pending at the time of this pre-merge log.

## Delivered

- Added `make portfolio-demo` for isolated PostgreSQL, Temporal, workflow
  worker, FastAPI Runtime, and production-built Next.js Web startup, with
  bounded readiness, logs, normal stop, exact-volume reset, and process-safe
  lifecycle ownership.
- Added a deterministic API-only Scene B driver for raw-byte mailbox
  verification, exact duplicate deduplication, PostgreSQL inbox/outbox/delivery
  authority, Temporal dispatch, delivered callback, two exact channel Evidence
  records, and browser-projection isolation.
- Added `make portfolio-demo-recovery`, reusing the accepted Phase 06B1 live
  lost-response/idempotent recovery test against isolated real PostgreSQL and
  Temporal.
- Documented the truthful two-scene demo, failure/restart procedure, expected
  results, portfolio bullets, two-to-three-minute narration, Gmail/Voice seams,
  limitations, and the unchanged Phase 03B `NO_GO_STOP_PHASE03B` result.

## Local evidence

- Fresh/reset `make portfolio-demo` started PostgreSQL on 55433, Temporal on
  7234, the worker, Runtime on 8000, and Web on 3000. Normal stop preserved the
  isolated volume; reset removed only
  `proxyloop-portfolio-demo_postgres-data` and produced a fresh next start.
- Scene B passed one verified inbound, one exact deduplicated replay, one
  accepted synthetic delivery, one delivered callback/receipt, two exact
  authoritative channel Evidence records, and browser-projection isolation.
- `make portfolio-demo-recovery` passed the live lost-response path with one
  logical local delivery.
- Full real-dependency regressions passed against isolated services: Phase 05A
  24 passed; Phase 06B1 31 passed.
- Phase 07A focused supervisor/scenario suite: 15 passed. New-file Ruff format
  and lint passed; strict mypy passed; `make preflight-fast` passed.
- Concurrent lifecycle checks passed: a second start failed closed, concurrent
  stop plus second start left stop successful, the second start rejected, and
  the original supervisor exited zero. Production Web build/start reached
  readiness without modifying tracked `apps/web/next-env.d.ts`.

## Browser/manual evidence

- A fresh Scene A completed the four-fact intake (`$92`, `$75`, hotspot kept,
  financing unchanged), Runtime Case creation, exact approval, one execution,
  and authoritative Evidence receipt.
- At 1280x900 and 375x812, the completed receipt remained visible, page width
  equaled viewport width, and no browser warning/error log was present.
- Stop followed by restart without reset recovered the same verified Case,
  offer, `execution count 1`, and Evidence receipt from authoritative state.
- After the supervisor changed from Next development mode to production
  build/start, final HTTP readiness passed and no Web source changed. A final
  extra Browser reload was blocked by the Browser tool's localhost URL policy;
  it was not bypassed and is not claimed as an additional passed observation.

## Independent review

- Initial Terra review requested an atomic single-instance lifecycle lock and
  the required closeout evidence.
- Rereview found and root fixed a narrower startup-vs-stop/reset sentinel race
  using one shared command mutex for start/stop/reset.
- Final Terra rereview: **Approve**, with no unresolved Blocking, Important, or
  Minor finding.

## Final gate

- The one stable-diff `make preflight` passed: Runtime Ruff and strict mypy
  passed (57 typed source files), Runtime tests passed 291 with 33 explicitly
  guarded infrastructure skips, ML Ruff/strict mypy passed (30 typed source
  files), and ML tests passed 177.
- Contract generation/drift, TypeScript contracts, Phase 01B/02/03A1/03B
  artifacts, Harness layout, Web lint/typecheck/47 tests/production build,
  both uv locks, frozen offline pnpm lock, script compilation, diff checks, and
  Compose configuration all passed.
- Hosted `phase-gate` and GitGuardian must pass on the final PR head before
  squash merge; their PR records remain authoritative.

## Unverified and deferred

No real Gmail/OAuth/token/inbox, MCP, Provider contact, SMS, LiveKit/SIP/Voice,
consumer authentication, real model, Phase 03 rerun/promotion, deployment,
release, production monitoring, production exactly-once, capacity, or
production-readiness path was run or authorized. Phase 06B2 and full Phase 07
remain separate unauthorized gates.
