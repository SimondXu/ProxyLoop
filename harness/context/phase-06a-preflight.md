# Phase 06A Preflight Audit

**Date**: 2026-08-26
**Baseline**: clean synchronized `main` at `e49adf8`
**Decision owner**: root Sol
**Decision**: `GO`

This file records activation-time evidence and frozen decisions. It does not
claim Phase 06A implementation, real-dependency verification, Browser success,
independent review, CI, or merge.

## Confirmed baseline

- Phase 05A is merged and the Harness was idle before the user's explicit Phase
  06A authorization.
- The existing Web already provides the API-connected four-fact conversation
  intake, Runtime-owned Case creation, Task Brief, Offer, exact Approval, and
  Evidence receipt; it is not a greenfield frontend.
- Web state is component memory only. It does not persist a Case locator, call
  GET Case, send Idempotency-Key, poll, or restore after refresh.
- The current Web protects only one session from late responses through a
  monotonic session ref and one-tab duplicate clicks through `busy`.
- API already exposes readiness, GET Case, and the unchanged POST wire contract.
  Temporal mode converts a strict Idempotency-Key UUIDv4 to command ID.
- API POST responses and GET Case project the current Runtime aggregate;
  PostgreSQL owns the durable Case state in Temporal mode.
- Phase 05A already implements command receipts, Update/Activity IDs, bounded
  retries, worker recovery, approval expiry, Continue-As-New, and CAS.
- Existing receipts identify only command ID/type/reference and do not prove
  that a reused key carried the same semantic command body; Phase 06A freezes a
  minimal internal fingerprint binding.

## Activation checks

- Proposal audit Web tests: 29 passed.
- Proposal audit Phase 05A API/Case Runtime tests: 11 passed; two guarded real
  PostgreSQL tests skipped because no test database variable was supplied.
- No real PostgreSQL/Temporal, Browser, disconnect, multi-tab, channel, Provider,
  model, credential, deployment, or release check was run at activation.

## Rejected alternatives

- No frontend rewrite or visual redesign: existing UI already matches the
  conversation-first goal.
- No new status endpoint: GET Case plus readiness expose the necessary
  authoritative state for this one-Case local slice.
- No SSE/WebSocket: POST is synchronous to transition completion and bounded GET
  polling is sufficient for reconnect, pending execution, and expiry.
- No generic SWR/state/retry framework: the journey has one narrow client and
  one active Case.
- No Phase 06B channel work: external identity, PII/retention, webhook security,
  outbox/reconciliation, delivery receipt, and credentials need a separate gate.

## Primary evidence read by Sol

- `harness/status.toml`, `PLANS.md`, Phase 05A contract/review/log;
- current `apps/web` page, workspace, Runtime client, rewrite, UI docs, and tests;
- API app/config/readiness, workflow client/workflow/activity, Case Runtime
  commands/repository/PostgreSQL/runtime, and Phase 05A tests;
- Durable Orchestration, State Ownership, Agent Decision Loop, and Safety and
  Reliability Invariants in `docs/architecture.md`;
- the two user-referenced prior Codex tasks, used only as orientation and then
  checked against current source.

## Stop boundary

Stop and request a new user decision if implementation requires a new canonical
public body/schema, SSE/WebSocket, auth, real Provider/model/channel/credential,
outbox/reconciliation, destructive persistence work, a second Case/journey, a
visual redesign, production claim, deployment/release, or Phase 06B.
