# Phase 04C — Persistent Case Store

**Status**: In progress. Explicitly approved on 2026-08-25 from synchronized
`main` at `abe6e50`. This is one bounded Phase 04 control-plane slice; it does
not complete the broader Serving and Control Plane phase or authorize Phase 05.

## Objective

Make the existing fictional-telecom `ThinAgentRuntime` restart-safe at its
business-state seam by adding one PostgreSQL `CaseRepository` adapter with
strict aggregate serialization and transactional revision compare-and-swap.
The current local Web/API journey must survive a Runtime reconstruction from
pending approval through verified terminal Evidence without changing its HTTP
or canonical-contract interface.

## Frozen module and interface

- The existing `CaseRepository.create/get/replace` protocol is the storage
  seam. It remains unchanged unless primary implementation evidence proves one
  acceptance criterion impossible; any change then requires Sol to amend this
  contract before implementation continues.
- `InMemoryCaseRepository` remains the default local/test adapter.
- Add one `PostgresCaseRepository` adapter owned by `runtime/services/api`.
  Storage connections, schema bootstrap, JSON encoding, strict decoding,
  transaction handling, SQL errors, and revision CAS remain hidden behind the
  existing repository interface.
- Persist one versioned JSONB aggregate per Case with the Case UUID and current
  snapshot revision as indexed relational columns. Do not normalize every
  canonical contract into duplicated SQL tables in this slice.
- Stored JSON must include the snapshot, visible event history, execution
  count, source pins, action intent, approval, and capability proposal. Every
  read validates the storage envelope and all nested canonical Pydantic models
  before returning authoritative state. Unknown envelope fields and unsupported
  envelope versions fail closed.
- Never pickle Python objects or serialize private
  `FictionalMobileProvider` attributes. Reconstruct only the current
  deterministic fictional Provider from the validated Case, offer, action
  intent, approval, completion, and Evidence state. Reconstruction must verify
  that simulator-derived offer/confirmation identities match persisted
  authoritative state.
- A PostgreSQL replacement is one transaction whose write succeeds only when
  `case_id` exists and the stored revision equals `expected_revision`.
  Duplicate create, missing replacement, and stale replacement preserve the
  current stable `CaseConflictError` / `CaseNotFoundError` behavior.

## Restart and idempotency boundary

- The current protocol persists `pending_execution=true` plus exact model
  pins, intent, approval, and proposal before fictional Provider execution.
  PostgreSQL CAS must make this claim single-winner across separate Runtime
  instances.
- A Runtime reconstructed while waiting for approval must accept only the
  exact persisted revision/approval/action pins and then complete once.
- A Runtime reconstructed from a pending execution claim must deterministically
  replay the local fictional simulator transition, persist one canonical
  confirmation/Evidence result, clear `pending_execution`, and report
  `execution_count=1`.
- A reconstructed terminal Case must return the same completion and Evidence;
  duplicate approval is a terminal read and must not append Evidence or
  increase the execution count.
- These claims apply only to the deterministic fictional simulator. The phase
  does not claim exactly-once real external effects after a crash. Durable
  provider event IDs, an outbox, reconciliation, Temporal activities, and real
  side-effect recovery remain later gated work.

## Configuration and schema

- Process configuration defaults to memory storage.
- PostgreSQL requires an explicit storage-mode selection and a non-empty
  database URL. Invalid mode or incomplete configuration fails before serving.
- Scripted/model selection remains independent from memory/PostgreSQL storage
  selection; scripted + PostgreSQL is the required local restart path.
- Add the smallest synchronous PostgreSQL driver compatible with the current
  synchronous Runtime. Do not add SQLAlchemy, Alembic, an ORM, a pool, a generic
  repository framework, or a new service package.
- Schema bootstrap may create one namespaced application table with
  `CREATE TABLE IF NOT EXISTS`. Stored payload versioning owns later migration
  detection; automatic destructive migration is forbidden.
- Database URLs, passwords, raw stored payloads, and exception bodies must not
  be returned by the HTTP surface or recorded in Harness evidence.

## In scope

- one PostgreSQL repository adapter and private storage envelope/compiler;
- explicit memory/PostgreSQL Runtime construction;
- one minimal schema bootstrap path;
- repository round-trip, duplicate, missing, stale-CAS, malformed-payload, and
  unsupported-version tests against real PostgreSQL;
- separate-Runtime waiting-approval restart, pending-execution restart, and
  terminal duplicate-approval tests against real PostgreSQL;
- a cross-instance CAS race proving only one pending execution claim wins;
- a disposable local PostgreSQL test path and a hosted CI PostgreSQL gate;
- minimal Runtime/infrastructure/architecture documentation and Harness
  evidence for this bounded slice.

## Acceptance criteria

1. `CaseRepository` callers and the HTTP request/response contracts are
   unchanged; ordinary `ThinAgentRuntime()` still uses memory storage.
2. Explicit PostgreSQL mode constructs the existing Runtime with a real
   `PostgresCaseRepository`; missing URL, invalid storage mode, schema/bootstrap
   failure, malformed stored payload, and unsupported stored version fail
   closed without leaking credentials or raw database errors.
3. PostgreSQL create/get/replace strictly round-trip every non-Provider
   `CaseRuntimeState` field and reconstruct a validated fictional Provider at
   offered, awaiting-approval, pending-execution, rejected, and confirmed
   states.
4. Duplicate create, missing replace, and stale revision replace preserve the
   current stable domain errors. Two repository/Runtime instances racing the
   same expected revision cannot both claim the update.
5. A Case created and advanced to pending approval by Runtime A can be loaded
   by newly constructed Runtime B, approved with the exact persisted pins, and
   completed with one execution and matching confirmation Evidence.
6. A simulated crash after fictional Provider commit but before final
   repository replacement leaves a persisted pending claim. A newly
   constructed Runtime completes recovery with one canonical execution result,
   clears the claim, and does not duplicate persisted Evidence.
7. Runtime C can load the terminal Case and repeat the same approval without
   changing revision, execution count, completion, or Evidence.
8. The existing memory repository concurrency, failure, model-adapter, API,
   and Web behavior remains unchanged.
9. Local focused checks use a disposable PostgreSQL database and pass without
   touching a developer's ordinary application data. Hosted PR CI runs the
   real PostgreSQL integration gate.
10. Affected Ruff, strict mypy, focused Runtime tests, Web regressions,
    `git diff --check`, repository layout, and final `make preflight` pass.
11. A fresh independent Terra reviewer has no unresolved Critical, Important,
    or Minor defect before the PR gate; Sol reads every changed source file and
    owns the final phase decision.
12. The final PR passes hosted `phase-gate` and GitGuardian, is squash merged,
    and the fully merged short branch is safely cleaned. Harness status then
    returns to idle and no next phase is authorized.

## Explicitly out of scope

- promoted Fast-model serving, a new model gateway, model fallback/rollback or
  load/OOM/p95 serving claims;
- model downloads, external model/API calls, training, reruns, data expansion,
  evaluation expansion, or promotion;
- Temporal, workflow workers, timers, signals, long-running waits,
  continue-as-new, durable activity retries, or a production outbox;
- real tools or Providers, external side-effect reconciliation, Gmail, MCP,
  authentication, webhooks, channels, voice, deployment, or release;
- production UI, another journey/vertical, intake/API redesign, canonical
  public contract/schema changes, or a general persistence framework;
- destructive schema migration, production credentials, consumer PII, or any
  claim that this local portfolio slice is production-ready.

## Frozen ownership

- Sol owns this contract/context/status, the SQL/storage/restart semantics,
  scope and phase-gate decisions, complete-diff review, documentation truth,
  durable review/log evidence, Git integration, and every completion claim.
- One Luna xhigh implementer owns product implementation in
  `runtime/services/api`, affected Runtime integration tests, runtime
  dependency/lock changes, the disposable Postgres test path, focused Make/CI
  wiring, and minimal Runtime/infrastructure documentation. It must not edit
  this contract, status, planning files, `PLANS.md`, ML/data artifacts, or
  unrelated Web behavior.
- One Terra high reviewer later owns read-only defect-first review and may run
  verification. The reviewer does not edit, commit, push, or merge.

## Verification plan

1. Red: add focused tests for Postgres repository behavior, explicit storage
   configuration, cross-instance CAS, approval restart, pending-claim restart,
   and terminal repeat; confirm the missing adapter/configuration fails.
2. Green: implement the smallest adapter, strict envelope, fictional Provider
   reconstruction, configuration, and disposable real-Postgres test path.
3. Focused: run affected Runtime tests, Postgres integration, Ruff, strict
   mypy, Web regressions, layout, and diff checks while behavior changes.
4. Review: Sol reads all changed source and the complete diff, then obtains
   fresh independent Terra evidence. Batch accepted remediation and rerun only
   affected gates until the diff is stable.
5. Broad: run `make preflight` once after the material diff stabilizes and
   record its exact outcome. Keep real Postgres focused evidence separate if
   the ordinary preflight intentionally remains infrastructure-independent.
6. Publish: write one concise log, close status truthfully, commit/push/open the
   bounded PR, wait for fresh CI/GitGuardian, approve and squash merge only
   after every criterion passes, verify clean synchronized `main`, safely
   remove only the fully merged branch, and stop before Phase 05.
