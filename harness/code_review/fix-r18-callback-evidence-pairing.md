# Review: callback events on a terminal Case are paired with their Evidence (R-18)

**Target**: `fix/r18-callback-evidence-pairing` into `main` (build-plan PR-4)

**Reviewer**: independent `reviewer` agent; findings recorded by the root.

**Verdict**: Approve with three Minors. All three accepted by the root and
fixed on the branch.

## Minor 1: an exact duplicate callback pair was accepted

`_verify_delivery_callback_pairs` paired by count, order and time only, so a
real callback event copied with `event_cursor + 1` (same `event_id`) plus the
same Evidence appended again passed. In normal operation each delivery status
yields one pair (ids `H(delivery_id:status)`), so duplicate ids are only
possible by forgery.

**Disposition**: fixed. Callback event ids and `PROVIDER_EVENT` Evidence ids
must be unique across the snapshot, else the same pairing error.
`test_an_exact_duplicate_of_a_callback_pair_is_rejected` was red before the
fix (did not raise) and is green after.

## Minor 2: forgery tests asserted only the generic wrapper

The tests matched "Case state failed storage validation", which any earlier
storage check also raises.

**Disposition**: fixed. `_assert_unpaired` also asserts the suppressed context
is the pairing `ValueError` ("terminal Case callback events do not match their
Evidence").

## Minor 3: adjacent cases untested

**Disposition**: fixed. Added: only `observed_at` shifted, only `captured_at`
shifted, callback Evidence moved before the confirmation Evidence, and the
exact duplicate pair.

## Accepted limits (unchanged)

A consistent forged pair with fresh ids, a delivered/bounced text swap, and
unchecked `source_ref`/`content_hash` remain accepted limits; binding a pair
to a real delivery needs a storage change (see the fix log).

## Gate

Non-DB checks green after merging `main` @ `c73f6a7` (`make lint`,
`make typecheck`, `make test`, `make preflight`). The serial DB/Temporal gates
on the merged branch are pending.
