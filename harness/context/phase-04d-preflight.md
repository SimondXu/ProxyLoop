# Phase 04D Preflight Audit

**Date**: 2026-08-25
**Baseline**: synchronized `main` at `e64fa85`
**Decision owner**: root Sol
**Decision**: `GO`

## Confirmed evidence

- `harness/status.toml` was idle with no active contract or authorized next
  phase before activation.
- Phase 04A provides the local deterministic Runtime; Phase 04B provides an
  explicit no-retry typed model adapter and fake-transport failure tests;
  Phase 04C provides memory/PostgreSQL repository selection, strict aggregate
  persistence, revision CAS, restart/recovery proof, and a real PostgreSQL CI
  service.
- FastAPI currently has stable model, not-found, and conflict responses but no
  operation record, correlation ID, liveness/readiness endpoints, or stable
  storage-unavailable HTTP category.
- Model and storage modes are already explicit and independent. No automatic
  fallback path exists.
- PostgreSQL construction and operations already suppress raw driver causes;
  a concrete read-only readiness query can reuse the same connection seam
  without changing the three-method Case repository interface.
- `ThinAgentRuntime` remains the only application consumer. Architecture
  explicitly defers extracting a transport-neutral Runtime until a worker or
  another consumer exists.

## Decision rationale

The missing operational evidence can be localized inside the existing API
module with allowlisted records, a read-only dependency probe, deterministic
fake faults, and a local diagnostic runner. None requires Temporal, a real
model/Provider, credentials, canonical contract changes, deployment, or
production claims. The authorized Phase 04D scope is therefore executable.

## Primary files read by Sol

- `AGENTS.md`, `harness/status.toml`, `PLANS.md`, and `GOALS.md`;
- Phase 04A, 04B, and 04C contracts plus the Phase 04C review/log;
- `docs/architecture.md` and the Phase 04 control-plane section of the product
  specification;
- `runtime/services/api` app/config/server/runtime/repository/PostgreSQL source;
- `runtime/packages/agent_core` coordinator and scripted adapter seams;
- `runtime/packages/openai_adapter` adapter/error taxonomy;
- affected Phase 04A/04B/04C integration tests, `Makefile`, and hosted CI.

## Non-goals reaffirmed

No Temporal, real external call, credential, model promotion/training,
canonical contract change, deployment/release, authentication/channel/voice,
destructive migration, or automatic fallback is authorized.
