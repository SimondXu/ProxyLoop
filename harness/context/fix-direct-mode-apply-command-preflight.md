# Fix: direct mode shares the command path, expires approvals, and says what it is (P1 B2-4, E-4, E-11, B2-6)

Bounded change under `harness/context/audit-remediation-decisions.md`
decision 8 ("Direct mode routes POSTs through `apply_command` (honours
`Idempotency-Key`), in-process expiry timer, documented one-Case limit").
Branch `fix/direct-mode-apply-command` from `main`.

## Defects (audit `harness/code_review/repo-audit-B2.md` §B2-4, §B2-6; `repo-audit-E.md` §E-4, §E-11)

- **B2-4** Direct-mode branches of `POST /cases`, `/cases/{id}/events`,
  `/cases/{id}/approvals/{id}` (`app.py` ~399-512) call
  `service.create_case/append_event/approve` and never read
  `Idempotency-Key` (`_command_id` is reached only in Temporal branches).
  Repro `b2/s1_direct_keys.py`: same key twice on `POST /cases` → 201 then 409
  `case already exists`; `Idempotency-Key: not-a-uuid` accepted; same key +
  exact body twice on `/approvals` → 200 then 409 `case snapshot revision is
  stale`. Temporal mode returns byte-identical deduplicated payloads. Mode
  divergence: a pin-less approval re-POST after terminal → direct 200
  (`_repeat_approved`), Temporal 409; `test_phase_04a_agent_runtime.py`
  (~115-123) asserts the direct 200.
- **E-11** Direct mode never expires an approval (`EXPIRE_APPROVAL` is issued
  only by the Temporal timer); the Web parks on "Approval deadline reached"
  forever although `state-matrix.md:17` promises the Runtime labels it.
- **B2-6** When `completion_decision is None` the API emits `not_done` /
  `approval_or_execution_pending` unconditionally, including after a rejected
  or expired approval.
- **E-4** `runtime-client.ts` `statusMessage("case_conflict")` says "I will read
  its current authoritative state before continuing" but the component
  performs no read; `restorePersisted` refuses every non-Temporal/Postgres
  profile, and direct readiness emits no `orchestration_mode`, so every
  reload lands on "Recovery requires the durable … profile"; one Case per
  process means every later `POST /cases` is 409 and nothing says "restart
  the Runtime process" (`docs/ui/user-flows.md:50-51`, `state-matrix.md:18`,
  `apps/README.md:12-16`).

## Frozen design

1. **One command path.** In direct mode every POST builds the same
   `CaseCommandRequest` the Temporal branch builds (with
   `command_id=_command_id(request)`), converts it with
   `.to_command(occurred_at=<runtime clock>)` and calls
   `service.apply_command(command)`, then
   `service.current_result(case_id, transition=transition)` — exactly the
   Temporal branch's tail. A malformed `Idempotency-Key` is rejected with the
   same status/category in both modes. Remove the mode-divergent behaviour:
   after this change the key/body matrix (same key + same body → identical
   deduplicated payload; same key + different body → conflict; no key → fresh
   command; malformed key → rejected; pin-less re-POST after terminal → the
   Temporal-mode response) is identical in both modes. Delete
   `_repeat_approved` if `apply_command` no longer reaches it; otherwise make it
   return what Temporal mode returns. Update the 04a test that asserts the
   direct 200 (intended consequence; say so in the log).
2. **In-process expiry (direct mode only).** When a direct-mode command
   returns a transition with a pending approval (`approval_id`,
   `approval_expires_at`), schedule one asyncio task on the app's loop that
   sleeps until `approval_expires_at` and then issues `EXPIRE_APPROVAL` through
   the same `apply_command` path, with a deterministic command id derived
   the way the workflow derives its expiry command id (reuse the helper if
   importable). At most one timer per approval; a no-op receipt if the
   approval was decided meanwhile; tasks cancelled on app shutdown (lifespan);
   failures logged, never crash the app. Inject the clock/sleep so tests do
   not wait. Documented limit: direct mode is in-memory — a process restart
   loses the Case and its timer.
3. **Honest completion projection (B2-6).** When `completion_decision is
   None`, derive `reason_codes` from the approval state: pending →
   `approval_or_execution_pending`; rejected → `approval_rejected`; expired →
   `approval_expired`; no approval → `approval_or_execution_pending` as today.
   `decision` stays the projection value `not_done` (the browser projection
   is not a canonical contract).
4. **Honest Web copy (E-4).** Readiness in direct mode emits
   `orchestration_mode: "direct"` (and live/ready payloads stay otherwise
   unchanged). The Web shows, for a direct profile, the documented one-Case
   limit and "restart the Runtime process to start over" instead of the
   durable-profile recovery block; `statusMessage("case_conflict")` no longer
   promises a read the component does not perform (either perform the read
   through the existing reconnect path, or change the copy — pick the smaller
   change consistent with `state-matrix.md` and say which). Update
   `apps/README.md` and the cited docs lines to match the behaviour.
5. Out of scope: multi-Case direct mode, durable direct mode, R-1 (cached
   Update failure after retryable exhaustion), any Temporal-mode change.

## Regression tests (write first)

- API, both modes (parametrise direct vs the fake-Temporal client used by the
  existing Temporal API tests): the key/body matrix above on all three POST
  routes — fails on main in direct mode.
- Direct-mode expiry: create → event (pending approval) → advance the
  injected clock past `approval_expires_at` → the approval is persisted
  `expired` exactly once, the completion projection says `approval_expired`;
  a decision before the deadline cancels/no-ops the timer.
- B2-6 projection after reject and after expire.
- Web: direct readiness shows the one-Case/restart copy and no durable
  recovery block; `case_conflict` copy matches behaviour.

## Verification

Focused API + Web tests; `make web-check`; `make lint`; `make typecheck`;
`make preflight-fast`. Compose gates are run by the root serially.
