# Fix: callback events on a terminal Case are paired with their Evidence (R-18)

Backlog item R-18 in `harness/context/audit-remediation-status.md` §4a
(build-plan PR-4). Branch `fix/r18-callback-evidence-pairing` from `main` @
`d23aff9` (includes #75, R-10).

## Defect (observed on main)

R-10's terminal rule in `_reconstruct_provider` (`postgres_repository.py`)
admits only delivery-callback `provider_event`s after the approval-decision
cursor, but recognizes a callback by type, actor and fixed text alone. It
does not pair the event with the Provider-event Evidence the same callback
appended, so the codec accepts:

- any number of callback events after the approval cursor with no Evidence;
- a callback event deleted while its Evidence remains;
- a Provider-event Evidence with no callback event;
- a callback Evidence whose time differs from its event.

## What both sides carry

`record_channel_delivery` (`runtime.py`) appends, in one write, one event and
one Evidence at the tail of the snapshot:

| Event | Evidence |
|---|---|
| `event_id = H(case:event:channel-delivery:{delivery_id}:{status})` | `evidence_id = H(channel-delivery-evidence:{delivery_id}:{status})` |
| `event_cursor = previous + 1` | appended last in `snapshot.evidence` |
| `occurred_at = event_time` | `observed_at = captured_at = event_time` |
| `content` = delivered / bounced text | `source_type = PROVIDER_EVENT`, `source_ref = provider_message_id`, `content_hash = artifact_hash` |

The delivery id is not stored in the Case payload, so neither id can be
re-derived and the status is not bound to the Evidence. What both sides share
is order and time. `PROVIDER_EVENT` Evidence is produced only by
`record_channel_delivery`. The execution appends the simulator-transition and
the confirmation Evidence last, and a first callback is refused while
`pending_execution` is set, so a callback after the approval always lands
after the confirmation Evidence.

## Rule (implemented)

`_verify_delivery_callback_pairs`, called from the terminal branch of
`_reconstruct_provider` after the confirmation and simulator-transition
Evidence are verified:

> Let `E` be the events with `event_cursor > approval_cursor`, in cursor
> order (R-10 already requires each to be a delivery callback), and `V` the
> `PROVIDER_EVENT` Evidence after the confirmation Evidence, in tuple order.
> Then `len(E) == len(V)` and, for each `i`,
> `V[i].observed_at == V[i].captured_at == E[i].occurred_at`.

No contract change, no storage change, no `storage_version` bump.

## Compatibility

- Terminal rows written since R-10 (#75): every callback after the approval
  was written by `record_channel_delivery`, which appends one event and one
  `PROVIDER_EVENT` Evidence with equal times, after the confirmation Evidence.
  An exact replay adds neither. These rows decode unchanged.
- Terminal rows written before R-10: the old rule required the source-pin
  cursor to equal the snapshot cursor, so no event followed the approval;
  `E` is empty, and no `PROVIDER_EVENT` Evidence follows the confirmation
  Evidence (nothing else appends Evidence to a terminal Case). They decode.
- Legacy storage version 1 and stored 1.0 snapshots keep the Evidence order;
  the 1.0 test below covers a callback on a 1.0 COMPLETE Case.
- Non-terminal path: the check runs only in the terminal branch. Callbacks
  before the approval (event cursor at or below the cursor, Evidence before
  the confirmation Evidence) are outside both `E` and `V`.

## Tests (`tests/integration/test_r10_terminal_delivery_callback.py`)

Codec round-trip without a database. Red on `main` for the five forgeries;
the controls pass on both.

- Rejected: forged callback event without Evidence (after a real callback,
  and on a completed Case with none); deleted callback event with its Evidence
  kept; extra `PROVIDER_EVENT` Evidence without an event; callback Evidence
  one second off its event.
- Accepted: the existing single `delivered` / `bounced` callback and its exact
  replay; two callbacks after COMPLETE (`delivered` then `delivered` or
  `bounced`, two deliveries); one callback before the approval and one after
  COMPLETE; the existing 1.0 and rebuilt-event controls.

## Known limits (not fixed here)

- A consistent forged pair (event and Evidence with equal times) is accepted,
  and a delivered/bounced text swap is not detected: binding a pair to a real
  delivery needs the delivery id, either stored in the payload or checked
  against `proxyloop_channel_delivery_receipts.evidence_id`. That is a storage
  or repository-design change for the root.
- `source_ref` and `content_hash` are not checked; the event does not carry
  them.
- Callbacks before the approval stay unpaired, and extra Evidence placed
  before the confirmation Evidence or of other types is not restricted, as
  before.
