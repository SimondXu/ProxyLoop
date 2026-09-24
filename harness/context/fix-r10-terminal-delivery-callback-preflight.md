# Fix: a delivery callback on a COMPLETE Case survives the PostgreSQL codec (R-10)

Backlog item R-10 in `harness/context/audit-remediation-status.md` §4a.
Branch `fix/r10-terminal-delivery-callback` from `main` @ `f818b61`.

## Defect (observed on main)

The 06B1 contract requires a delivery callback on a terminal Case to append a
Provider-event Evidence and advance the revision. `record_channel_delivery`
(`runtime.py`) does so, which moves `pins.event_cursor`. The codec's terminal
rule in `_reconstruct_provider` (`postgres_repository.py`) demanded
`execution_source_pins == snapshot.pins`, i.e. it assumed a terminal Case is
never written again, so the write fails with "Case state failed storage
validation" (Temporal: non-retryable `state_invalid`; inbox stays `reserved`).
For a stored 1.0 COMPLETE Case the callback's `_snapshot(...)` also defaulted
to 1.1, which requires a completion receipt the 1.0 Case does not have.

`tests/integration/test_phase_06b1_channel_runtime.py` covered the callback
with an in-memory repository that never ran the codec.

## Decision (root): fix A

1. The terminal rule becomes
   `execution_source_pins == snapshot.pins.model_copy(update={"event_cursor": c})`,
   where `c` is the cursor of the deterministic `approval_decision` event
   (event id `_stable_uuid(f"{case_id}:event:approval:{approval_id}:approved")`,
   exactly one, `occurred_at == approval.decided_at`), and every event after
   `c` must be a delivery-callback `provider_event` (actor Provider, one of the
   two fixed callback texts).
2. The delivery callback passes `schema_version=snapshot.schema_version` once
   `completion_decision` is set, so a 1.0 COMPLETE Case stays 1.0.

Rejected: B (write channel tables only; violates 06B1 AC 9), C (refuse the
callback; loses the receipt), D (store the cursor; heavier, storage change).
No contract change, no `storage_version` bump.

## Tests (`tests/integration/test_r10_terminal_delivery_callback.py`)

A `_ChannelRepository` variant round-trips every write through
`PostgresCaseRepository._encode_state` / `_decode_state` (no database).

- First callback after COMPLETE (`delivered` and `bounced`): revision +1;
  completion decision, receipt and execution source pins unchanged; event text
  and Provider-event Evidence asserted; a replayed observation of the same
  delivery is still accepted.
- DB-gated, in `test_phase_06b1_channel_runtime.py` (`make phase06b1-check`):
  the same flow on `PostgresCaseRepository`, re-read through a fresh instance.
- A stored 1.0 COMPLETE Case stays 1.0 after the callback.
- A source-pin cursor of `c ± 1` is rejected.
- A non-delivery event after the approval decision (consumer message,
  `provider_event` with other content, other event type) is rejected; a
  control rebuilds the genuine callback event the same way and is accepted.
