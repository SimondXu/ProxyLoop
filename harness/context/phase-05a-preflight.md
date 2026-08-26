# Phase 05A Preflight Audit

**Date**: 2026-08-26
**Baseline**: clean synchronized `main` at `95ac99c`
**Decision owner**: root Sol
**Decision**: `GO`

This file records activation-time evidence and frozen decisions. It does not
claim implementation, Temporal/PostgreSQL test success, review, CI, or merge.

## Confirmed repository evidence

- `harness/status.toml` was idle after Phase 04D and Phase 05A was waiting for a
  new explicit user decision. The current request explicitly authorizes the
  Phase 05A proposal and implementation.
- Phase 04C provides strict PostgreSQL aggregate persistence, version CAS,
  deterministic fictional Provider reconstruction, pending-execution recovery,
  and guarded real-PostgreSQL tests.
- Phase 04D provides redacted operation taxonomy, process/storage readiness,
  explicit adapter/storage selection, fake fault evidence, and no silent
  fallback.
- `ThinAgentRuntime` currently owns the complete application loop inside the
  API service. Architecture explicitly says to extract it when a durable worker
  becomes the second consumer; Phase 05A now satisfies that condition.
- Runtime already persists the exact approval/pins/proposal pending claim before
  fictional execution and writes completion/Evidence through PostgreSQL CAS.
  Temporal can call this logic but must not duplicate or supersede it.
- Canonical contracts already include `ApprovalDecision.EXPIRED` and
  `EventActor.SYSTEM`; the Runtime lacks only the expiry transition command.
- Compose already declares Temporal 1.28.1 plus PostgreSQL, while hosted CI
  currently runs only the real PostgreSQL Phase 04C gate.

## Confirmed external SDK evidence

Drift-prone SDK behavior was checked against official Temporal Python SDK and
Temporal documentation on 2026-08-26:

- official SDK docs were checked and the repository's compatible resolver
  selected `temporalio` 1.32.0;
- Update-with-Start requires an explicit Workflow ID conflict policy; using
  `USE_EXISTING` sends the Update to a running Workflow or starts one when none
  is running;
- update handlers can run concurrently, so command application needs one
  workflow-safe serialization lock and handlers must finish before
  Continue-As-New;
- time-skipping uses `WorkflowEnvironment.start_time_skipping()` and replay uses
  `Replayer` against captured Workflow history;
- expected domain failures must use typed `ApplicationError` handling because
  ordinary unexpected Workflow exceptions retry Workflow tasks.

Official sources:

- <https://python.temporal.io/temporalio.client.Client.html>
- <https://github.com/temporalio/sdk-python>
- <https://github.com/temporalio/samples-python>
- <https://docs.temporal.io/develop/python>

## Frozen seam decision

- Move Runtime and repository implementation inward as one package because the
  Runtime and durable repository form one application-state module. Keep API
  modules as re-export adapters so extraction does not break callers.
- Temporal history contains commands and compact transition references only.
  After an Update, API reads PostgreSQL to construct the existing response.
- Persist command receipts in the same PostgreSQL aggregate/CAS write as the
  business transition. This is the cross-retry and cross-Continue-As-New
  idempotency authority; Temporal Update and Activity IDs are additional
  orchestration deduplication layers.
- Keep Temporal mode scripted + PostgreSQL only. Model and memory Temporal modes
  would weaken the approved fault and single-truth claims and are rejected.

## Primary files read by Sol

- `harness/status.toml`, Phase 05A row in `PLANS.md`, Phase 04C/04D contracts;
- required Durable Orchestration, State Ownership, Agent Decision Loop, and
  Safety and Reliability Invariants in `docs/architecture.md`;
- API `runtime.py`, `repository.py`, `postgres_repository.py`, `app.py`, config,
  readiness, exports, package configuration, Makefile, Compose, and hosted CI;
- complete Phase 04A, 04C, and 04D integration test files;
- canonical approval/event enums and approval validation.

## Fault and evidence boundary

The phase must prove Update/Activity idempotency, PostgreSQL receipt dedup,
worker restart, post-commit retry, timer/approval race, replay, time-skipping,
and Continue-As-New. It explicitly cannot prove real external-effect exactly
once behavior because no Provider event ID, outbox, or reconciliation module is
authorized.

## Non-goals reaffirmed

No real Provider/tool/channel/model/credential, outbox/reconciliation, auth,
voice, production UI, deployment/release, training/evaluation/playbook work,
canonical wire redesign, production exactly-once, multi-tenancy, or capacity
claim is active.
