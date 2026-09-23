# Fix: a corrected retry is not replayed a cached Update failure (P1 C-4)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Branch `fix/update-id-body-binding` from `main`.

## Defect (audit C-4, `harness/code_review/repo-audit-C.md` §C-4)

`TemporalCaseDispatcher` (`workflow_worker/client.py`) sends each command as
a Workflow Update whose ID is `update_id_for_command(command_id)`
(`workflow.py:58`) — the command id only. Temporal caches an Update's outcome
per Update ID within a run, so once an Update with that ID fails
non-retryably (e.g. `case_conflict` from a stale `expected_revision`), the
**same command id with a corrected body** is answered with the cached
failure until Continue-As-New. Repro `c4`: `APPEND_EVENT` with a wrong
`expected_revision` → `case_conflict`; same command id with the correct
revision → `case_conflict` again; `runtime.apply_command` directly → revision 4.
The mailbox path is worse: the inbox reservation fixes `command_id`
(`app.py` channel route) and `expected_revision` is read outside any lock, so
a channel event whose first dispatch conflicted is poisoned until
Continue-As-New.

## Frozen design

1. The Update ID binds the command id **and** the semantic request body:
   `update_id_for_command(command_id, request_fingerprint)` →
   `f"{COMMAND_ID_PREFIX}{command_id}:{request_fingerprint[:16]}"` (keep the
   prefix; lower-case). `request_fingerprint` is the same semantic
   fingerprint the runtime stores on the receipt
   (`case_runtime.commands.semantic_command_fingerprint`, which excludes
   `occurred_at` and includes `expected_revision`), computed from the command
   the dispatcher sends. If the dispatcher's request type is not a
   `CaseCommand`, compute the fingerprint over the exact fields that become
   the `CaseCommand` (document which); never include wall-clock or
   workflow-assigned fields.
   - Identical retries (same id, same body) keep the same Update ID →
     Temporal dedup still returns the cached outcome (success or failure).
   - A corrected body gets a new Update ID → reaches the runtime, where the
     existing receipt/fingerprint rules decide: no receipt → executes; a
     receipt with a different fingerprint → the existing conflict.
2. Activity IDs (`activity_id_for_command`): check Temporal's uniqueness rule
   for activity IDs within one workflow execution. If two sequential Updates
   for the same command id could collide, bind the activity ID the same way;
   otherwise leave it and say why in the log.
3. Any other code that parses or reconstructs Update IDs (workflow, replay
   tests, continue-as-new carry-over, readiness) is updated consistently.
   Workflow determinism: histories recorded under the old ID format must
   still replay (the existing Replayer test must stay green); if an ID is
   computed inside workflow code, gate the change with `workflow.patched`
   rather than breaking replay.
4. Out of scope: moving the channel `expected_revision` read under a lock
   (the new Update ID makes the retry path correct; note the residual race in
   the log), direct mode (B2-4), any runtime receipt rule.

## Regression tests (write first; Temporal time-skipping pattern in `tests/integration/test_phase_05a_temporal_workflow.py`)

- **T1 (fails on main)**: `APPEND_EVENT` with a stale `expected_revision` →
  `case_conflict`; the same command id with the correct `expected_revision`
  → succeeds (revision advances).
- **T2**: an identical retry of a failed command returns the same failure
  without re-executing; an identical retry of a successful command returns
  the stored receipt (`deduplicated` semantics unchanged).
- **T3**: same command id, different body after a **successful** first
  command → the runtime's existing fingerprint conflict (not a second
  execution).
- **T4 (if cheap, Phase 06B1 channel)**: a mailbox event whose first dispatch
  conflicted succeeds on redelivery once the revision is current.
- Unit: `update_id_for_command` is stable, lower-case, prefix-preserving, and
  differs when `expected_revision` differs.

## Verification

Focused module(s); `make lint`, `make typecheck`, `make preflight-fast`.
Real-dependency gates (`phase05a-check`, `phase06b1-check`, `postgres-check`)
are run by the root serially.
