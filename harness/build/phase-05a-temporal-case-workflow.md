# Phase 05A — Temporal CaseWorkflow

**Status**: Complete. Explicitly approved by the user on 2026-08-26 from clean,
synchronized `main` at `95ac99c`. This is one bounded durable-orchestration
slice for the existing fictional telecom Case. It does not authorize Phase 06
or any real external effect.

## Go decision

**GO**. Phase 04C provides PostgreSQL aggregate truth and cross-process CAS;
Phase 04D provides redacted dependency readiness and deterministic fault
evidence. Temporal is now a real second consumer of the Case application
Runtime, so extracting that Runtime inward is justified. The Workflow remains
an ordering and recovery module; it does not become a second business store or
authorization module.

## Objective

Implement one PostgreSQL-backed, scripted/fake, fictional-Provider-only
Temporal `CaseWorkflow` that durably orders Case commands, waits for approval,
fires the approval-expiry timer, retries activities, survives worker restart,
and periodically Continues-As-New. PostgreSQL remains the sole authoritative
Case, approval, Evidence, command-receipt, and completion store. Existing
Policy, Approval, Executor, Evidence, and Verifier semantics retain authority.

## Frozen modules and seams

- Add inward package `runtime/packages/case_runtime` with import package
  `proxyloop_case_runtime`. It owns the shared `ThinAgentRuntime`,
  `CaseRepository`, `CaseRuntimeState`, memory/PostgreSQL adapters, command
  application, command receipts, and current-result projection.
- `runtime/services/api` becomes an HTTP/control-plane adapter. Its existing
  `proxyloop_api.runtime`, `repository`, and `postgres_repository` modules stay
  as compatibility re-export shims. Existing top-level `proxyloop_api` imports
  remain valid.
- `runtime/services/workflow_worker` becomes the Temporal adapter/service with
  import package `proxyloop_workflow_worker`. It owns `workflow.py`,
  `activities.py`, `client.py`, `config.py`, `readiness.py`, and the worker
  entry point. Workflow code may import only deterministic command/reference
  types and Temporal workflow APIs; all database, model, simulator, clock,
  network, and business transition work runs in activities.
- `ThinAgentRuntime.create_case`, `append_event`, and `approve` remain
  compatible. Add one deep application interface,
  `apply_command(CaseCommand) -> CaseTransitionRef`, for the Temporal activity.
  Existing direct callers need not construct commands.
- Explicit API orchestration mode is `direct` or `temporal`. `direct` remains
  the default and preserves current memory/PostgreSQL behavior. `temporal`
  requires scripted model mode, PostgreSQL storage, a database URL, a Temporal
  address/namespace/task queue, and a ready Temporal dependency; incomplete or
  incompatible configuration fails before serving. There is no silent
  fallback between orchestration modes.
- In Temporal mode, POST Case endpoints use Update-with-Start for creation and
  Update for an existing running workflow. GET reads the current authoritative
  PostgreSQL aggregate directly and never treats Workflow state as Case state.

## Frozen internal command contracts

These are strict, versioned internal application/orchestration contracts. They
are not canonical public wire contracts and do not change generated schemas.

### `CaseWorkflowInput`

- `schema_version: Literal["phase-05a-v1"]`
- `case_id: UUIDv4`
- `run_generation: int >= 0`
- `commands_in_run: int >= 0`
- `continue_as_new_after: int` with process default `32` and test override in
  the inclusive range `1..1000`
- `last_transition: CaseTransitionRef | None`

The input contains no Case snapshot, offer, approval body, Evidence body,
Provider state, model output, prompt, credential, database URL, or arbitrary
exception text.

### `CaseCommand`

Common fields:

- `schema_version: Literal["phase-05a-v1"]`
- `command_id: UUIDv4`
- `case_id: UUIDv4`
- `command_type: Literal["create_case", "append_event",
  "decide_approval", "expire_approval"]`
- `occurred_at: timezone-aware UTC datetime`, supplied from deterministic
  Workflow time in Temporal mode
- `expected_revision: int | None`

Type-specific fields:

- `create_case`: the existing four intake facts only;
- `append_event`: non-empty `content` and existing allowlisted
  `consumer_message` event type;
- `decide_approval`: `approval_id`, approved/rejected decision, and optional
  expected Case/action-intent revisions;
- `expire_approval`: `approval_id`, exact expected snapshot revision, and exact
  approval expiry timestamp copied from the preceding transition reference.

Strict validation rejects unknown fields, unsupported versions/types,
non-UTC time, wrong command-specific field combinations, and a command whose
Case ID does not match the Workflow input.

### `CaseTransitionRef`

- `schema_version: Literal["phase-05a-v1"]`
- `command_id`, `case_id`, and `command_type`
- `before_revision: int | None`, `after_revision: int`
- `event_cursor: int`
- stable deterministic `route: str`
- `approval_id: UUIDv4 | None`
- `approval_expires_at: UTC datetime | None`
- `terminal: bool`
- `deduplicated: bool`

It is the only business reference returned by an activity or carried through
Continue-As-New. The first application stores the same reference with
`deduplicated=false` in PostgreSQL; duplicate application returns an equivalent
reference with `deduplicated=true` and performs no Case write, Provider commit,
Evidence append, revision increment, or event increment.

## Workflow, Update, Activity, and command identity

- Workflow ID: `proxyloop-case/{lowercase-case-uuid}`. One scripted Case maps
  to one long-running Workflow execution chain.
- Update name: `apply_case_command`.
- Update ID: `case-command/{lowercase-command-uuid}`.
- Activity type: `apply_case_command_activity`.
- Activity ID: `case-command/{lowercase-command-uuid}`. Temporal activity
  retries reuse the scheduled Activity ID; Continue-As-New may create a later
  run, while PostgreSQL receipt deduplication remains authoritative across runs.
- The optional HTTP `Idempotency-Key` header is a strict lowercase UUIDv4 and
  becomes `command_id`. If absent, the API creates a fresh UUIDv4. A caller
  that wants retry deduplication must reuse the same header. The create command
  uses the existing deterministic fictional fixture Case ID; a second distinct
  create remains a conflict, preserving current single-fixture behavior.
- Update-with-Start uses `WorkflowIDConflictPolicy.USE_EXISTING`; its start
  operation uses `WorkflowIDReusePolicy.REJECT_DUPLICATE`. A start operation
  object is constructed per call and never reused.
- Update handlers validate synchronously, then serialize all activity dispatch
  through one workflow-safe lock. PostgreSQL CAS and command receipts remain
  authoritative against cross-worker, retry, callback, or non-Temporal races.

## Activity retry and non-retryable taxonomy

The workflow schedules each command activity with start-to-close `30s`,
schedule-to-close `2m`, and bounded retry policy: initial interval `1s`,
coefficient `2.0`, maximum interval `10s`, maximum attempts `5`.

Retryable:

- `storage_unavailable` / transient psycopg connection or transaction failure;
- worker process loss, activity timeout, or task redelivery;
- explicitly injected transient activity failure before or after an
  authoritative PostgreSQL commit. A post-commit retry must hit the stored
  command receipt.

Non-retryable:

- `invalid_command`, unsupported schema/type, non-UTC time, or wrong Case ID;
- `case_not_found`;
- `case_conflict`, including stale CAS, terminal mutation, approval pin
  mismatch, approval already terminal, or Case awaiting another command;
- `approval_expired` for a late consumer decision after the timer transition;
- `state_invalid` for malformed/unsupported stored business state;
- any model path in Temporal mode, because Phase 05A is scripted-only.

Expected non-retryable failures become stable typed Temporal
`ApplicationError`s with redacted messages. Duplicate command receipt is a
successful result, not an error. Unexpected defects are bounded by the same
maximum-attempt policy and must not expose exception bodies through HTTP.

## Approval wait and expiry transition

- A transition that returns a pending approval ID and expiry arms exactly one
  durable workflow timer for that exact reference.
- A consumer approval/rejection Update and the timer race under the same
  workflow lock. The first PostgreSQL CAS transition wins; the loser observes
  the authoritative receipt/state and cannot execute a stale offer.
- When the timer wins, `expire_approval` writes the existing canonical
  `ApprovalDecision.EXPIRED`, sets `decided_at` to the exact `expires_at`,
  appends one `EventActor.SYSTEM` `approval_expired` visible event, preserves
  zero execution/Evidence, clears the approval wait, and returns `fast_now`.
- A late approval is a stable non-retryable conflict. It never changes the
  expired approval, invokes the fictional Provider, or creates Evidence.

## Continue-As-New carry state

- Continue-As-New occurs after `continue_as_new_after` completed command
  handlers when no handler/activity is in progress. It never interrupts an
  Update handler.
- Carry only: schema version, Case ID, incremented run generation, command
  count reset to zero, unchanged threshold, and the last
  `CaseTransitionRef` (including a pending approval/expiry reference when
  present).
- Do not carry Case snapshots, visible event bodies, model work, Provider
  objects, Evidence bodies, arbitrary command history, or credentials.
- PostgreSQL command receipts preserve idempotency across the execution chain.
  On the new run, a pending approval reference re-arms the remaining timer from
  deterministic Workflow time; an elapsed deadline immediately dispatches the
  expiry command.

## Frozen fault-injection matrix

| Fault | Expected proof |
|---|---|
| Duplicate Update/callback with same command ID | Same transition reference, one Case transition, one Provider execution, one Evidence pair |
| Client loses response after Update acceptance | Retrying same Update ID/command ID returns authoritative result without duplicate write |
| Worker stops before activity starts | Replacement worker processes the queued command |
| Worker/activity stops after PostgreSQL commit before activity completion | Retry returns stored command receipt; revision/Evidence/execution stay singular |
| PostgreSQL unavailable for fewer than five attempts | Activity retries and succeeds after recovery |
| PostgreSQL unavailable through retry exhaustion | Stable redacted failure; Workflow remains available for a later distinct command |
| Stale revision or approval/action pin | Non-retryable conflict; no retry storm or mutation |
| Approval Update races expiry timer | Exactly one CAS winner; no stale execution after expiry |
| Workflow worker restart while waiting approval | Durable timer/wait resumes and accepts exact pinned decision |
| Continue-As-New with pending approval | New run carries only reference/control state and preserves remaining timer |
| Duplicate old command after Continue-As-New | PostgreSQL receipt deduplicates across runs |
| Replay current captured histories | No nondeterminism failure |
| Time-skipping past expiry | Canonical expired transition occurs without wall-clock wait |
| Temporal unavailable at API readiness/dispatch | Explicit 503/redacted category; no direct-mode fallback |

This matrix proves durable orchestration only for the deterministic fictional
Provider. It makes no real external exactly-once, outbox, reconciliation,
multi-tenant, throughput, latency, or capacity claim.

## In scope

- this build contract, activation preflight, status, minimal roadmap and
  architecture/runtime documentation truth;
- inward Runtime/repository package extraction with API compatibility shims;
- command contracts, PostgreSQL command receipts, exact expiry transition, and
  application command interface;
- Temporal workflow worker, activities, client/config/readiness, worker CLI;
- explicit API Temporal mode using Update-with-Start/Update;
- direct memory and existing direct PostgreSQL behavior unchanged;
- real guarded PostgreSQL + Temporal integration, fault injection, replay,
  time-skipping, duplicate callback, worker recovery, and Continue-As-New
  tests;
- focused Make/CI/Compose wiring, independent review, final preflight, and one
  concise Phase log.

## Acceptance criteria

1. All frozen contracts, identity/idempotency rules, retry taxonomy, expiry,
   Continue-As-New state, and fault rows are implemented without canonical
   wire-schema drift.
2. `proxyloop_case_runtime` is the inward owner; every prior supported
   `proxyloop_api` import and direct memory call remains compatible.
3. Temporal Workflow history/carry state contains only commands and transition
   references, while PostgreSQL alone validates and returns authoritative
   Case/approval/Evidence/completion state.
4. Direct mode remains default and passes existing 04A/04B/04C/04D and Web
   tests unchanged. Temporal mode rejects memory/model combinations and never
   silently falls back.
5. In explicit Temporal mode, create uses Update-with-Start and later POSTs use
   Update; returned HTTP payloads are projected from PostgreSQL after the
   transition reference and retain existing JSON/status behavior.
6. Activity retry/non-retryable behavior matches the taxonomy and redacts
   driver/Temporal exception details.
7. Approval expiry persists one canonical expired/system-event transition;
   timer/approval races cannot execute a stale offer.
8. Duplicate command/update/callback and post-commit activity retry produce one
   business transition, one fictional Provider commit, and one Evidence pair.
9. Worker restart, pending-approval recovery, Continue-As-New carry/re-arm,
   cross-run duplicate receipt, replay, and time-skipping tests pass.
10. Guarded real PostgreSQL and real Temporal integration tests pass locally
    and in hosted CI without touching ordinary developer application data.
11. Affected Ruff, strict mypy, lock/layout/diff, prior Runtime/Web regression,
    and one stable-diff `make preflight` pass.
12. Fresh independent Terra review has no unresolved Critical, Important, or
    Minor defect; Sol reads every changed source and owns final integration.
13. Hosted `phase-gate` and GitGuardian pass; the bounded PR is squash merged,
    the fully merged short branch is safely cleaned, status returns idle, and
    Phase 06 remains unauthorized.

## Explicitly out of scope

- real Provider, tool, channel, email, voice, webhook, MCP, or credential;
- real model call, model serving/promotion/training/evaluation/playbook work;
- outbox or reconciliation implementation for real external effects;
- auth, production UI, deployment, release, destructive migration;
- canonical public wire-contract/schema redesign;
- production exactly-once, multi-tenancy, throughput, latency, capacity,
  autoscaling, availability, or production-readiness claims.

## Frozen ownership and review

- Root Sol owns this contract/status, shared interfaces, idempotency/expiry/
  retry semantics, security and scope decisions, complete-diff review,
  verification truth, Git integration, and every completion claim.
- Product implementation may be delegated only after this contract is frozen,
  with non-overlapping file ownership and exact verification commands.
- One fresh Terra high reviewer later owns read-only defect-first review of the
  stable full diff and adversarial fault cases. The reviewer does not edit,
  commit, push, or merge.

## Verification plan

1. Activate this contract/status and capture the preflight evidence.
2. Red: add focused command/expiry/compatibility and Temporal workflow tests.
3. Green: extract inward Runtime, add receipts/expiry, then add Temporal
   workflow/activity/client/config/readiness and explicit API dispatch.
4. Focused: run unit/type/lint, prior 04A/04C/04D suites, guarded PostgreSQL,
   real Temporal, time-skipping, replay, and Web regressions while behavior
   changes.
5. Review: Sol reads every changed source and the full diff; obtain fresh Terra
   review, batch accepted remediation, and rerun affected gates.
6. Broad: run `make preflight` once on the stable reviewed diff and record exact
   passed/skipped/blocked/unrun evidence.
7. Publish: write one concise log, commit/push/open the bounded PR, wait for
   hosted CI/GitGuardian, squash merge only after every gate passes, return to
   clean synchronized `main`, safely clean the merged branch, and stop before
   Phase 06.

## Stop conditions

Stop and request a new user decision if any criterion requires a real external
effect, outbox/reconciliation, credential, canonical wire redesign, model work,
production claim, deployment/release, destructive migration, or scope beyond
this fictional scripted workflow. Otherwise continue through integration and
stop with Phase 06 unauthorized.
