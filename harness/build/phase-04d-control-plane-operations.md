# Phase 04D — Control-Plane Operations and Failure Evidence

**Status**: Complete; independently approved on 2026-08-26. Authorized from
synchronized `main` at `e64fa85` after root Sol's read-only audit. This is one
bounded Phase 04 operational-evidence slice. It does not authorize Phase 05A
or Temporal.

## Go decision

**GO**. The current FastAPI and `ThinAgentRuntime` application module can own
request operation records and readiness without extracting a second Runtime,
changing canonical contracts, dispatching a real model, or introducing a
durable worker. Existing explicit model/storage configuration is sufficient
for controlled rollback; this phase must prove that behavior rather than add
automatic fallback.

## Objective

Establish credential-safe, measurable local control-plane operation and
failure evidence around the existing scripted/fake-model and
memory/PostgreSQL Runtime. The result prepares later Temporal fault injection
without promoting a model or claiming production readiness.

## Frozen modules and interfaces

- Keep `ThinAgentRuntime` and all application orchestration in
  `runtime/services/api`; do not extract a transport-neutral Runtime before a
  second consumer exists.
- Add one API-owned operation-observation module with a small recorder
  interface. It emits exactly one allowlisted JSON record per HTTP operation
  and supports an in-memory test adapter. Records may contain correlation ID,
  operation/route template, Case ID and revision, deterministic route,
  configured adapter/storage mode, policy/approval/execution/verifier outcome,
  stable error category, status, and latency. They must never contain request
  or response bodies, raw prompts, event content, database URLs, credentials,
  exception bodies, or arbitrary headers.
- Add one API-owned readiness module. Liveness is process-only. Readiness
  checks only configured local dependencies: memory is immediately ready and
  PostgreSQL performs a read-only `SELECT 1`. Model mode is configuration
  metadata only; readiness must not dispatch a model or probe a remote base
  URL. Readiness never reads or mutates a Case.
- Keep `CaseRepository.create/get/replace` unchanged. A concrete PostgreSQL
  readiness method is outside that business-state interface.
- Add a stable internal storage-unavailable exception category. HTTP and CLI
  surfaces expose only fixed redacted messages. Malformed/unsupported stored
  business state continues to fail closed and is not relabeled as dependency
  availability.
- Keep existing model/storage process selection explicit and independent.
  `scripted` versus `model` and `memory` versus `postgres` remain operator
  choices; no failure automatically switches an adapter or repository.
- Add one deterministic local diagnostic runner. It uses fresh in-process
  scripted Runtime journeys and injected fake model failures only, records
  request p50/p95, error rate, timeout rate, wall/CPU/RSS observations, and
  environment metadata, and labels all output local diagnostic evidence.

## Stable operation taxonomy

The operation record uses allowlisted categories. The minimum required set is:

- success: `none`;
- storage: `storage_unavailable`;
- model: `model_configuration`, `model_timeout`, `model_transport`,
  `model_invalid_output`, `model_metadata`, `model_stale_pins`, and
  `model_result_rejected`;
- Case control: `case_not_found`, `stale_cas`, and `case_conflict`;
- readiness/internal: `dependency_not_ready` and `internal_error`.

Existing HTTP Case response bodies and status codes remain compatible. New
liveness/readiness responses are control-plane-local and do not become
canonical Case contracts.

## Acceptance criteria

1. Each Case HTTP request and health/readiness request emits exactly one
   correlated structured operation record with only the frozen allowlist.
   Successful Case records cover Case/revision, deterministic route,
   adapter/storage mode, policy/approval/execution/verifier outcome, response
   status, stable `none` error category, and latency.
2. Model, storage, stale-CAS, not-found, conflict, proposal-rejection, and
   unhandled failure paths emit the stable category without raw request,
   payload, prompt, credential, database URL, header, or exception text.
3. `GET /health/live` reports process liveness without dependency work.
   `GET /health/ready` verifies the configured memory/PostgreSQL dependency
   without model dispatch or Case read/write and returns stable redacted 503
   behavior when unavailable.
4. Storage unavailable, model timeout/transport/invalid output, stale CAS, and
   pending fictional execution recovery have deterministic fault-injection
   coverage and stable redacted HTTP/CLI behavior.
5. A frozen no-credential diagnostic profile runs the existing scripted flow
   plus fake failures, records p50/p95, error rate, timeout rate, and local
   resource observations, and rejects unexpected statuses/categories. Its
   result is explicitly not a production capacity, real-model latency, OOM,
   autoscaling, or promoted-serving claim.
6. Explicit adapter/configuration rollback is proven with no silent fallback.
   A Case written to PostgreSQL through a fake model-backed Runtime remains
   readable and safely continuable after an explicit switch to scripted mode.
7. Existing `CaseRepository`, HTTP Case contracts, canonical contracts,
   deterministic authority, Web behavior, memory behavior, PostgreSQL
   restart/CAS/recovery, and Phase 04B fake-transport behavior remain
   compatible.
8. Focused Runtime/fault/profile/PostgreSQL checks, affected Ruff and strict
   mypy, Web regressions, layout/lock/diff checks, one independent Terra
   review, and one final stable-diff `make preflight` pass.
9. One concise execution log and durable independent-review artifact record
   exact passed, skipped, blocked, manual, hosted, and unrun evidence.
10. The final PR passes hosted `phase-gate` and GitGuardian, is squash merged,
    and the fully merged short branch is safely cleaned. Harness status then
    returns to idle with Phase 05A unauthorized.

## Explicitly out of scope

- Temporal SDK, workflow worker, activities, workflows, timers, signals,
  durable retries, continue-as-new, or any Phase 05 implementation;
- real Provider/tool/channel, outbox, provider-event reconciliation, or real
  exactly-once claims;
- model download, real model/API call, training, rerun, promotion,
  vLLM/SGLang deployment, load/OOM/production p95 claims, automatic fallback,
  production rollout, deployment, or release;
- authentication, production secret manager, schema normalization,
  destructive migration, voice, channels, production UI, or another vertical;
- canonical wire-contract/schema changes, Runtime extraction, generic
  telemetry platform, metrics backend, distributed tracing backend, or broad
  repository framework.

## Frozen ownership

- Root Sol owns this contract/status, module seams, taxonomy, readiness and
  redaction policy, scope/gate decisions, complete-diff review, Harness and
  documentation truth, Git integration, and all completion claims.
- One Luna xhigh implementer may own bounded product changes in
  `runtime/services/api`, the Phase 04D integration tests and diagnostic
  script/artifact, focused Make/CI wiring, and minimal runtime/architecture
  documentation. It must not edit this contract, Harness status, planning
  files, canonical contracts, ML/data history, Web product flow, Temporal, or
  unrelated files.
- One fresh Terra high reviewer later owns read-only defect-first review and
  focused verification. It does not edit, commit, push, or merge.

## Verification plan

1. Red: add focused failing tests for record completeness/redaction,
   liveness/readiness, storage HTTP/CLI taxonomy, model failure categories,
   stale CAS, fake-model-to-scripted PostgreSQL switch, and diagnostic report
   schema/outcomes.
2. Green: implement the minimum operation observer, readiness probe, storage
   category, explicit profile metadata, and diagnostic runner.
3. Focused: run Phase 04D plus affected 04A/04B/04C Runtime suites, real
   disposable PostgreSQL checks, Ruff, strict mypy, profile validation, Web
   regressions, lock/layout, and diff checks while behavior changes.
4. Review: Sol reads all changed source and the complete diff, then obtains a
   fresh Terra review. Batch accepted findings and rerun affected checks.
5. Broad: run `make preflight` once after the material diff is stable and
   reviewed. Keep the real PostgreSQL and local diagnostic evidence explicit.
6. Publish: record the review/log, close status to idle, commit, push, open the
   bounded PR, wait for fresh CI/GitGuardian, squash merge only after every
   gate passes, verify synchronized clean `main`, clean only the fully merged
   branch, and stop at the Phase 05A gate.

## Stop condition

Stop and request a new user decision if any acceptance criterion requires a
canonical wire-contract change, Temporal/Phase 05, real external calls or
credentials, model work, deployment, destructive migration, or another scope
expansion. Otherwise complete integration and stop with Phase 05A unauthorized.
