# Phase 06B1 Local Controlled Mailbox Execution Log

**Date**: 2026-08-26
**Baseline**: integrated `main` at `40e324f`
**Branch**: `codex/phase-06b-controlled-channels-proposal`
**Status**: Bounded product phase complete and returned to idle. Phase 06B2 is
unauthorized. PR/hosted integration remains pending at the time of this
pre-merge log.

## Delivered

- Added one strict, credential-free `local_mailbox` connector with exact raw-
  byte SHA-256 fixture verification, five-minute unknown-event freshness,
  immutable delivery attempts, deterministic provider-message identities, and
  bounded fault injection.
- Added server-owned PostgreSQL channel binding, inbox, outbox, and delivery
  receipt state with exact replay classification, monotonic observations, and
  atomic Case-plus-first-outbox and Case-plus-receipt transactions.
- Added Phase 06B1 internal Case commands and one separate Temporal delivery
  activity while preserving old Phase 05A command/history decoding.
- Added one API-only synthetic ingress route with stable redacted categories.
  Existing Case GET responses filter channel material from a copied browser
  projection while retaining Phase 06A revisions, cursors, pins, approval,
  completion, and receipt behavior.
- Preserved the conversation UI, four-fact intake, Case recovery, approval,
  polling, and Evidence flow without changing Web source or browser storage.

## Review evidence

- Initial Terra review found browser channel-material exposure and missing
  restart reconciliation.
- Rereview found that unseen lookup could fabricate acceptance after a known
  pre-accept failure; the adapter now returns Unknown and uses exact idempotent
  resend only when neither adapter nor PostgreSQL has accepted truth.
- Final remediation short-circuits persisted accepted/delivered/bounced state,
  rejects missing provider identity and terminal failure, and fail-closes every
  unrecognized stored state before any adapter call.
- Final Terra rereview: Approve with no unresolved Blocking, Important, or
  Minor finding.

## Local evidence

- Real disposable PostgreSQL plus Temporal `make phase06b1-check`: 31 passed,
  covering strict verification, replay/freshness, API redaction, atomic
  rollback, lost response, fail-before-accept, persisted truth, idempotent
  replacement retry, duplicate Update, workflow replay, and corrupt-state
  rejection.
- Real disposable PostgreSQL plus Temporal `make phase05a-check`: 24 passed,
  covering the prior Case, approval, expiry, retry, worker recovery,
  Continue-As-New, and replay behavior.
- Affected Runtime Ruff and strict mypy passed; the final strict mypy run
  checked 25 source files. `git diff --check` passed.
- Existing Web gate passed: lint, TypeScript typecheck, 47 focused tests, and
  production build. No Web source was changed.
- Browser smoke completed the unchanged four-fact intake, Case creation, exact
  approval, and final authoritative Evidence receipt. At 1280x900 and 375x812
  there was no horizontal overflow and no console warning or error.

## Final gate evidence

- The first final-preflight attempt stopped immediately at Ruff format-check on
  two newly changed function signatures. Ruff mechanically formatted only
  those signatures; no behavior changed and the attempt did not enter lint,
  typecheck, tests, or builds.
- The corrected sandboxed attempt passed formatting, Ruff, diff checks, both
  mypy lanes, and 275 Runtime tests with 33 guarded infrastructure skips, then
  stopped because the sandbox prohibited the existing Phase 04B localhost
  black-box test from binding `127.0.0.1`. This was an environment permission
  failure, not a product assertion failure.
- The corrected stable diff passed `make preflight` outside that socket
  restriction: Runtime 276 passed with 33 guarded infrastructure skips, ML 177
  passed, Web lint/typecheck/47 tests and production build passed, and all
  contract/artifact drift checks, Ruff, both strict mypy lanes, both uv locks,
  frozen offline pnpm, Harness layout, script compilation, diff checks, and
  Compose configuration completed successfully.
- Hosted `phase-gate` and GitGuardian must pass on the final PR head before
  squash merge; their PR check and merge records remain authoritative.

## Stop boundary

No real Provider, email, MCP, SMS, voice, credential, authentication, external
network channel, production UI, deployment, release, production exactly-once,
multi-tenant, capacity, or production-readiness claim is authorized. Phase
06B2 requires a separate explicit user decision.
