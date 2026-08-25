# Phase 04A Preflight

Date: 2026-08-24

This file records activation-time observations only. It does not claim that
Phase 04A implementation tests or its final gate have run.

## Activation evidence

- Phase 03A1-R/V is squash merged through PR #11 as `e501e0f`.
- The Phase 03A1-R/V CI phase-gate and GitGuardian checks passed.
- The active branch is `feat/phase-04a-thin-agent-runtime`, based on `e501e0f`.
- The worktree was clean at Phase 04A activation.
- Phase 04A is the single user-approved active implementation phase.

## Observed baseline

- `runtime/services/api/pyproject.toml` exists, describes the FastAPI
  control-plane service, and currently declares no dependencies; no FastAPI
  implementation surface is present there yet.
- Existing deep seams include the canonical contracts, `CaseCoordinator`,
  `DeterministicRouter`, typed Fast/Slow adapter protocols and scripted
  adapters, `CapabilityExecutor`, the fictional Provider simulator, Evidence,
  and deterministic completion verification.
- The observed missing seams are a replaceable in-memory Case store/event-log
  boundary, a thin orchestration service, and the minimal local API/CLI
  boundary needed to connect those existing modules.
- No `.codegraph/` directory is present in the repository.
- The Phase 03A1-R/V artifacts and their source-bound checks are historical
  evidence and must remain immutable during Phase 04A.

## Scope boundary

Phase 04A is local and simulator-backed. It does not start more model
evaluation, r6/r7 work, training, PostgreSQL, Temporal, real tools or
Providers, authentication, external channels, voice, UI, deployment, or
release work.

## Not yet observed

No Phase 04A implementation tests, focused runtime checks, independent review,
or final `make preflight` result is recorded here. Those belong to the later
implementation and integration gate.
