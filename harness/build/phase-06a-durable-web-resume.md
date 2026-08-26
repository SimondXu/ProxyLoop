# Phase 06A — Durable Web Case Resume and Progress

**Status**: Complete locally and independently approved on 2026-08-26 from
clean, synchronized `main` at `e49adf8`. Hosted integration is pending. This
phase extends the existing conversation UI over the completed
scripted/PostgreSQL/Temporal Case lifecycle. It does not authorize Phase 06B
controlled channels or any real external effect.

## Objective

Preserve the existing four-fact conversation intake and visual flow while
making an already-created fictional Case truthfully recoverable after page
refresh, connection loss, API restart, or worker restart. The Web must reuse
the current HTTP bodies and authoritative PostgreSQL projection, own stable
command identities for uncertain retries, reject stale responses, display
pending approval/expiry/pending execution/completion and dependency failures,
and show a receipt only after an authoritative recovery read.

## Frozen seams

- Keep `apps/web/app/page.tsx`, the three-column conversation shell, the four
  intake questions, Draft Task Brief, explicit create action, constraint event,
  exact approval, Offer, and Evidence receipt flow. No route-first wizard,
  detached form, new journey, or visual redesign.
- `apps/web/lib/runtime-client.ts` remains the only Web-to-Runtime seam. Add
  narrow readiness and GET Case reads plus an explicit `idempotencyKey` option
  on the existing three POST helpers. Do not add a BFF, framework, SSE,
  WebSocket, or new HTTP route.
- Reuse `GET /health/ready`, `GET /cases/{case_id}`, and the existing POST body
  schemas. Canonical generated public contracts do not change.
- Durable claims require explicit `orchestration_mode=temporal`,
  `storage_mode=postgres`, and `adapter_mode=scripted`. Direct/memory mode
  remains compatible but is not a durable-recovery proof.
- PostgreSQL remains the sole Case, approval, Evidence, completion, event, and
  command-receipt truth. Temporal remains the owner of ordering, retries,
  waits/timers, worker recovery, and Continue-As-New. Browser storage is only a
  locator and pending-command retry aid.

## Frozen browser persistence

Use one small versioned local-storage envelope containing only fictional demo
state:

- schema version;
- Runtime-returned active Case ID and confirmed four intake facts;
- at most one pending command with command kind, lowercase UUIDv4 key, exact
  request body, Case ID when known, and expected revision/approval pins;
- no credentials, auth token, arbitrary conversation transcript, hidden model
  text, Provider data, or real PII.

The Web validates the envelope strictly. Invalid or unsupported local data is
ignored and cannot become authoritative state.

## Frozen state rules

1. Intake before Case creation stays local and may be lost on refresh.
2. After create succeeds, persist only the Runtime-returned Case ID and the
   confirmed fictional facts, then recover through `GET /cases/{case_id}`.
3. Mount/reconnect first checks readiness and then reads the Case. A 503/network
   error preserves the locator and pending command; a 404 shows a bounded
   store-mismatch/reset message and never invents a Case.
4. Apply a response only when its Case ID and session generation match, its
   revision is greater than the current revision or its equal revision has an
   event cursor not lower than current, and all existing semantic validators
   pass. A late response cannot regress the UI.
5. `pending_execution=true` is a recoverable Finalizing state. A pending
   approval is actionable only before its returned expiry. Local clock expiry
   disables the button and triggers a read; only PostgreSQL may declare
   `ApprovalDecision.EXPIRED`.
6. Completion requires the existing verified-Evidence predicate and one final
   authoritative GET after the approval command. A terminal route alone is not
   success.
7. Bounded visibility-aware GET polling is allowed only while restoring,
   awaiting uncertain command resolution, pending execution, or crossing an
   approval deadline. Stop on stable approval, expired, verified receipt,
   blocked, or explicit user restart.
8. `New task` may clear local draft/session presentation but must not claim to
   delete the PostgreSQL Case or create a second fixed fixture Case.

## Frozen command identity and concurrency rules

- Before each semantic POST, Web creates one lowercase UUIDv4 with
  `crypto.randomUUID()`, persists the pending command, and sends it as
  `Idempotency-Key`.
- Network loss, timeout, 503, or lost response preserves the exact key and body.
  Retrying reuses both. A new user intent receives a new key.
- A 409 never causes automatic retry with a fresh key. Web reads current state,
  renders an already-applied effect when present, or discards a stale local
  command with an explicit conflict message.
- Within the current Case/Workflow, Runtime command receipts must bind a command
  ID to the normalized semantic command. Same key and same command deduplicate;
  same key with a different command type, body, Case identity, or pins in that
  Case fails closed with 409 and no mutation. This phase does not claim a global
  cross-Case command-key index; a second Case is out of scope.
  Existing receipts without a fingerprint remain decodable but cannot silently
  authorize a mismatched retry.
- Workflow serialization and PostgreSQL CAS remain the cross-worker and
  cross-client authority. No browser locking framework is required.

## Error UX

- network/disconnect: Case may still be progressing; preserve locator and offer
  reconnect/safe retry;
- dependency not ready or Temporal/storage unavailable: distinguish the stable
  redacted category, preserve state, and do not imply a failed business result;
- Temporal-unavailable/retry exhaustion: retain the same command identity,
  describe an orchestration attempt that did not finish rather than a business
  failure, and offer safe retry after authoritative read;
- stale/concurrent conflict: read and display the newer PostgreSQL state;
- approval expired: remove approval action and show the authoritative expired
  state;
- malformed/state-invalid/terminal-unverified: block success and retain the
  current fail-closed language.

## Acceptance criteria

1. The current conversation intake, correction, Task Brief, Offer, Approval,
   and receipt flow remains recognizable and existing tests keep passing.
2. No Runtime call occurs before explicit Case creation and no authoritative ID,
   revision, approval pin, Evidence, expiry, or completion is browser-created.
3. Reload restores an existing PostgreSQL Case by its Runtime-returned ID.
4. API and worker restart preserve pending approval, expiry, pending execution,
   and verified completion presentation through GET recovery.
5. Durable UX is enabled only against explicit Temporal/PostgreSQL/scripted
   readiness; direct mode makes no restart-recovery claim.
6. Every POST carries a stable browser-owned Idempotency-Key persisted before
   dispatch; uncertain retry reuses the exact key/body.
7. Within the current Case/Workflow, same-key/same-command duplicates produce
   one transition/execution/Evidence; same-key/different-command reuse returns
   409 without mutation. No global cross-Case key-uniqueness claim is made.
8. Duplicate clicks are suppressed and two stale concurrent commands yield one
   authoritative outcome; the loser recovers through GET.
9. Session, Case identity, revision, event cursor, Task Brief, approval, and
   Evidence validation prevent all late/stale response regression.
10. Browser time can disable an expired approval but only the authoritative GET
    result may label it expired.
11. Pending execution, reconnect, dependency readiness, stale conflict, expiry,
    and completion have truthful UI states. The existing redacted
    `temporal_unavailable` category truthfully covers an unfinished orchestration
    attempt, including retry exhaustion, without inventing a more specific wire
    category.
12. Bounded visibility-aware GET polling covers only unresolved states; no SSE,
    WebSocket, general data-fetching framework, or hidden background loop is
    introduced.
13. Receipt rendering follows a final authoritative GET and retains complete +
    one execution + nonempty matching Evidence requirements.
14. 404, 409, 422, 503, network failure, malformed local storage, malformed
    response, and terminal-but-unverified paths fail closed.
15. Focused Runtime/Web tests cover restore, lost response, key reuse, command
    mismatch, concurrent/stale handling, expiry, pending execution, readiness,
    receipt restore, and prior intake semantics.
16. Desktop and 375px Browser smoke pass without horizontal overflow or new
    console warning/error, and one stable-diff `make preflight` passes.
17. Fresh Terra review has no unresolved Blocking, Important, or Minor finding;
    hosted phase-gate and GitGuardian pass before squash merge.
18. Status returns idle after integration and Phase 06B remains unauthorized.

## Explicitly out of scope

- visual redesign, new route, wizard, form engine, generic state manager, SSE,
  WebSocket, second Case/journey/vertical, or post-create fact mutation;
- real Provider, tool, email, SMS, webhook, voice, SIP, channel, model call,
  credential, authentication, account, deployment, or release;
- outbox/reconciliation for real effects, destructive database reset/migration,
  production exactly-once, multi-tenancy, throughput, latency, capacity,
  autoscaling, availability, or production-readiness claims;
- Phase 06B controlled channels or Phase 07 work.

## Ownership and verification

- Root Sol owns this contract/status, shared interfaces, state/idempotency/
  security decisions, full-diff review, review reconciliation, final preflight,
  Git integration, and completion claims.
- One Luna xhigh implementer owns the frozen product/test/doc slice and may not
  edit Harness contract/status/review/log files, commit, push, or expand scope.
- One fresh Terra reviewer performs read-only defect-first review after the diff
  is stable. Accepted findings return to the same implementer.
- Run focused Web and Runtime checks while changing behavior, then Browser smoke,
  one final `make preflight`, one concise phase log, PR/CI/GitGuardian, squash
  merge, safe branch cleanup, and stop before Phase 06B.
