# Fix log: runtime execution claim receipt and same-command retry (P0-1)

Spec: `harness/context/fix-runtime-claim-receipt-retry-preflight.md`.
Resolves audit findings B2-1 / C-1 (Blocking), B2-2 / C-2 (Important);
review of the fix added one guard (channel callback during a pending claim).
Branch `fix/runtime-claim-receipt-retry` from `main` @ `5648ab4`.

## What changed

- `case_runtime/commands.py`: `ExecutionClaimRecord` (approval id, pinned
  revision, `claimed_at`, command id and fingerprint).
- `case_runtime/repository.py`: `CaseRuntimeState.execution_claim`, present
  iff `snapshot.pending_execution`.
- `case_runtime/runtime.py`: the claim write carries the record; a command
  arriving while the claim is pending is admitted by `_check_claim_retry`
  (same command id → same fingerprint required, old pin accepted; other
  commands → current pin or none) and re-drives `_execute_claim`;
  `_execute_claim` verifies at `claim.claimed_at`, skips the executor when
  the in-memory Provider is already confirmed, and rebuilds a cached
  executor whose `REUSED` answer is not backed by a confirmation; the final
  receipt uses the claim's `before_revision`; `record_channel_delivery`
  refuses a first callback while a claim is pending (replayed later).
- `case_runtime/postgres_repository.py`: envelope stores the claim; pending
  rows require it; the reconstruction gate also accepts a
  `CANDIDATE_COMPLETE` phase with a non-`COMPLETE` decision when execution
  finished (documented as defensive and unreachable with the simulator).

Not changed: `agent_core/capabilities.py` (P0-2), the timer path (P0-3),
`api/app.py` direct-mode command identity (B2-4, P1), `contracts.py`.

## Red → green

| Test | Red on `main` | Green |
|---|---|---|
| T1 `test_exact_pinned_retry_completes_pending_claim_after_final_write_failure` | 409 `case snapshot revision is stale` | 200 terminal, one confirmation |
| T2 `test_same_approval_command_retry_completes_pending_claim` | `CaseConflictError: case snapshot revision is stale` | terminal receipt, then `deduplicated=True` |
| T3 `test_late_pin_less_recovery_verifies_at_claim_time` | `needs_replan` | `complete` |
| T4 (Postgres) same-instance pinned retry / fresh-instance / late recovery | stale | converge; one persisted commit; envelope round-trips |
| T5 (Temporal) `test_live_temporal_approval_retry_after_final_write_outage_converges` | attempt 2 `case_conflict` | attempt 2 terminal |
| `test_delivery_callback_is_refused_while_execution_claim_is_pending` | `DID NOT RAISE ChannelConflictError` | refused, retry completes, replay accepted |

Root re-ran the audit's original reproductions `b2/s2_pending.py` and
`b2/s3_late_recovery.py` against the fix: exact retry → 200 terminal in
direct and fake-Temporal mode; T+2h recovery → `complete`, `route=terminal`.

## Checks

- Passed: focused suite (04A/04B/05A case runtime) 54 passed / 2 gated
  skips; `test_phase_06b1_channel_runtime.py` 17 passed; non-gated
  `tests/integration tests/contract` 261 passed / 37 skipped; `make lint`,
  `make typecheck`, `make format-check`.
- Passed (Compose `postgres`/`postgres-test`/`temporal`, torn down after):
  `make postgres-check` 27, `make phase05a-check` 26, `make phase06b1-check` 32.
- Passed: `make preflight` on the stable diff — runtime 307 passed / 37
  gated skips, ML 279, web 47, all artifact and layout gates valid.
- Independent review (`reviewer`, Opus): Request Changes → one Important
  (channel callback during a pending claim) fixed with the reviewer's
  direction and a load-bearing test; Minor "strict same-command comparison"
  deferred with B2-4 by root decision (spec amendment); T4 setup assertion
  moved; defensive gate commented. Adversarial probes by the reviewer:
  same id / different fingerprint → conflict; different id with old pin →
  stale; four concurrent same-command retries → one `deduplicated=False`,
  one Provider commit.
- Not run: hosted model calls; `make portfolio-demo*`.

## Known behaviour changes

- A persisted `pending_execution=True` row written before this change has
  no claim record and no longer decodes; a local demo database holding an
  in-flight claim from before the change must be reset. `storage_version`
  unchanged.
- In direct mode (no command identity, B2-4) an old-pin approval during a
  pending claim is admitted; completing the claim is idempotent.
- A local-mailbox delivery callback arriving during a pending claim is
  refused (`ChannelConflictError`) instead of silently rewriting the
  aggregate; the callback is replayed after the claim completes.
