# Phase 06A Durable Web Case Resume Execution Log

**Date**: 2026-08-26
**Baseline**: synchronized `main` at `e49adf8`
**Branch**: `codex/phase-06a-durable-web-resume`
**Status**: Bounded product phase complete and returned to idle. Phase 06B is
unauthorized. PR/hosted integration remains pending at the time of this
pre-merge log.

## Delivered

- Preserved the existing conversation-first four-fact intake, Task Brief,
  Offer, exact Approval, and Evidence receipt flow without a visual redesign.
- Added one strict versioned browser envelope for the Runtime-returned Case
  locator, confirmed fictional facts, and one exact pending command.
- Added explicit Idempotency-Key ownership before each POST, same-key exact
  retry, same-Case semantic receipt fingerprinting, GET-first conflict/lost-
  response resolution, and monotonic Case revision/event-cursor application.
- Added durable-profile readiness checks, reload/reconnect recovery, bounded
  visibility-aware polling, authoritative approval expiry, pending-execution
  Finalizing, and truthful network/dependency/Temporal error UX.
- Required a final PostgreSQL-backed GET before a completion receipt; Browser
  storage never becomes Case, Approval, Evidence, or completion authority.

## Review evidence

- Initial Terra review requested changes for envelope inconsistency,
  swallowed finalizing poll failures, and POST-before-GET recovery.
- Root found and remediated deadline hot-loop/backoff, polling-budget,
  visibility, retry-exhaustion-copy, and wall-clock test-fixture risks.
- Final Terra rereview: Approve with no unresolved Blocking, Important, or
  Minor finding; 47 Web tests and diff check passed in the final review.

## Local evidence

- Focused Web: 47 tests, ESLint, TypeScript typecheck, and production build
  passed without the timer-overflow warning from the rejected fixture.
- Focused Runtime: Ruff and strict mypy passed; the direct targeted suite passed
  13 tests with two guarded PostgreSQL cases skipped before the real gate.
- Real disposable PostgreSQL plus Temporal `make phase05a-check`: 24 passed,
  covering Case receipts, API, retry exhaustion, worker recovery,
  Continue-As-New, replay, expiry, and timer/update races after the Phase 06A
  receipt-fingerprint change.
- Browser against scripted/Temporal/PostgreSQL: a lost-response create recovered
  with the preserved pending command; Case refresh restored; pending approval
  survived worker shutdown; worker restart completed exact approval; final
  Evidence receipt survived refresh and API restart/reconnect.
- Browser layout: 1280px and 375px document widths matched viewport widths with
  no horizontal overflow. The final Browser console had no warnings or errors.
- The stale fixed Case left by the integration suite was isolated by rebuilding
  only the disposable `postgres-test` container and using a fresh local Temporal
  namespace; persistent PostgreSQL data and real external systems were untouched.

## Final gate evidence

- The first final-preflight attempt stopped immediately at Ruff format-check on
  one newly added test tuple; it did not enter lint, typecheck, or tests. The
  tuple was mechanically wrapped with no behavior change.
- The corrected stable-diff `make preflight` passed: Runtime 247 passed with 31
  guarded infrastructure skips, ML 177 passed, Web lint/typecheck/47 tests and
  production build passed, and all contract/artifact drift checks, Ruff,
  strict mypy, both uv locks, frozen offline pnpm, Harness layout, script
  compilation, diff checks, and Compose configuration completed successfully.
- Hosted `phase-gate` and GitGuardian must pass on the final PR head before
  squash merge; the PR check and merge records remain authoritative.

## Stop boundary

No real Provider/tool/channel, model call/credential, external-effect outbox or
reconciliation, auth, voice, visual redesign, second Case, deployment, release,
production exactly-once, multi-tenant, capacity, or production-readiness claim
is authorized. Phase 06B controlled channels requires a new user decision.
