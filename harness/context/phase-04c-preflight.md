# Phase 04C Preflight

Date: 2026-08-25

This file records activation-time observations and frozen decisions. It does
not claim implementation, PostgreSQL verification, independent review, CI, or
merge success.

## Activation evidence

- The user explicitly approved continuing along the recommended persistent
  control-plane route and instructed Codex to follow the repository Agents and
  Harness workflow.
- Local `main` and `origin/main` were synchronized and clean at `abe6e50`.
- `make preflight` passed immediately before authorization with Runtime 214,
  ML 177, and Web 29 tests plus all repository-native static, artifact, lock,
  build, layout, compilation, and Compose gates.
- Branch `feat/phase-04c-persistent-control-plane` was created directly from
  that baseline before planning or implementation files were written.
- The preserved `/private/tmp/proxyloop-ui-worktree` and its untracked planning
  files are unrelated user work and are not touched by this phase.

## Primary evidence and seam decision

- `CaseRepository` already exposes only create, get, and revision-CAS replace;
  `ThinAgentRuntime` receives it through constructor injection. PostgreSQL is
  therefore a second real adapter at an existing seam, not justification for a
  new generic repository framework.
- Seven of eight `CaseRuntimeState` fields are canonical Pydantic values or
  primitives. The remaining `FictionalMobileProvider` is a private mutable
  simulator object and must not be pickled or stored by private attribute.
- The canonical snapshot carries the Case, fixed offer, action intent,
  approval, completion, Evidence, events, and exact pins needed to reconstruct
  the current deterministic fictional Provider state and validate it.
- The Runtime persists an exact pending execution claim before simulator
  execution, but its executor idempotency cache and per-Case lanes are process
  local. PostgreSQL revision CAS can make the claim single-winner across
  processes; this phase cannot claim exactly-once real external effects.
- The frozen representation is one versioned, strictly validated JSONB
  aggregate row per Case. Normalizing every nested contract now would duplicate
  the canonical schema and widen the change without an observed query need.

## Observed dependency and test boundary

- `compose.yaml` contains PostgreSQL 17 and later Temporal services, but Runtime
  has no PostgreSQL driver, schema, migration, or database test today.
- The current synchronous FastAPI/Runtime path makes a synchronous psycopg 3
  adapter the minimum compatible driver. An ORM, migration framework, pool, or
  async repository is not justified in this slice.
- Current tests prove same-process concurrency, pending-claim CAS ordering,
  final-write retry, model fail-closed behavior, HTTP behavior, and Web
  completion. They do not prove cross-instance CAS or restart recovery.
- Current hosted CI has no PostgreSQL service. A real hosted database gate must
  be added; mocked SQL alone is insufficient evidence.

## Frozen recovery truth

- Waiting approval and terminal completion must survive a fresh Runtime and
  repository instance.
- Pending fictional execution may be deterministically replayed from the
  persisted claim after a fresh Runtime starts. Persisted completion and
  Evidence remain singular and authoritative.
- A real Provider call committed before a crash would require durable provider
  event IDs, reconciliation, and outbox/activity semantics that do not exist.
  This remains explicit later work and is not hidden behind the simulator test.

## Delegation evidence

- One read-only explorer mapped all stored fields, mutations, process-local
  idempotency, current tests, dependency conventions, and unresolved crash
  semantics. Sol independently read the required primary files and made the
  final aggregate/reconstruction/recovery decisions.
- One Luna xhigh implementer receives only the frozen product-code slice after
  this contract is active. Sol keeps the shared contract/status/docs and all
  architecture, authorization, completion, and integration decisions.
- One fresh Terra high reviewer will inspect the stable final diff and required
  adversarial cases before the PR gate.

## Scope boundary

No Temporal, real Provider/tool, real external effect, model execution,
training/evaluation work, authentication, channel, voice, production UI,
deployment, release, credential, PII, or next phase is active.
