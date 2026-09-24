# PR-13 Slow-driven intent and A-3 coordinator validator review

**Target**: `feat/pr13-slow-drives-intent` at head `e96d6f7`, on `main` @
`a8fdf5b`. Spec: `harness/context/pr13-slow-drives-intent-design.md`.

**Reviewer**: an independent read-only `reviewer` subagent. Its probes are in
`scratchpad/rev-pr13/`: `race.py`, `race_main.py`, `race_main2.py` and
`refresh_reject.py`.

**Recommendation**: Request Changes, with one Blocking finding (B1). The root
accepted every finding below and passed its decisions to the implementer.
The implementer wrote this file from the root's messages, not from the
reviewer's own text.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| B1 (Blocking) | A retry of a consumer event without `expected_revision` can pass `apply_command`'s receipt check before the first attempt writes, then wait on the Case lane and apply a second time. On the in-memory repository the race double-appended: two consumer events and two transitions for the command, with neither receipt marked as a duplicate. The PostgreSQL codec refuses such a state (a duplicate command in `transitions`). On main the first scripted turn's approval refused the retry by accident; PR-13 lets a turn apply without an approval. The root found the same issue as M-3 in the PR-11 review. | Applied in `9d24a3a`. `_check_not_applied(state, command_id)` runs inside the Case lane, before any model call or write, in `append_event`, `ingest_channel_event` and the receipt-deduplicated delivery write. It raises `CaseConflictError`, and `apply_command` returns the stored receipt marked `deduplicated`. Tests: `test_a_concurrent_retry_of_an_unpinned_event_applies_once[dialogue]` (strategy-only Slow, +1 min) and `[offer-expired]` (default Slow, +61 min), both unpinned, each ending with one consumer event, one transition, and no second model call; `test_a_retry_after_a_timeout_returns_the_stored_receipt`; `test_a_concurrent_retry_of_a_channel_ingest_makes_no_model_call`. The concurrent tests failed on the tree before the fix (the append race gave `(2, 2)` consumer and assistant events, and the channel race made a second Fast call), and a mutation run removing each re-check fails a test. Approve (approved and rejected) and expire already refused a replay in the lane with no write or trace; `test_the_lane_refuses_a_replayed_approval_command_without_a_write` pins that. Create has no lane. A raced create makes one extra Slow call and trace but writes no state, because the repository's create uniqueness refuses the second write; `test_a_raced_create_with_the_same_command_applies_once` pins the refusal. Rerunning `race.py` on the fix gives, for all 4 scenarios, one consumer event, one transition for the command, the second racer `deduplicated`, and a PostgreSQL encode that succeeds. |
| M5 | `record_channel_delivery`'s deduplicated-receipt branch appended a transition with the same `command_id` without re-checking the receipt under the lock, and a re-drive can send `expected_revision=None`. | Applied in two steps. In `9d24a3a` the deduplicated branch calls `_check_not_applied`. Test: `test_a_concurrent_retry_of_a_delivery_callback_records_once`, where the first write is held inside the lane while the unpinned retry reads the inbox; it fails without the check. That commit's claim that the first-callback branch needs no check was **wrong**. The in-lane receipt re-lookup and the first-callback write are separate `with self._lane(...)` blocks, so two unpinned same-command callbacks can both pass the re-lookup, and the second write then failed storage validation (`RuntimeError`) instead of returning a duplicate. The re-review reproduced this with `scratchpad/rev-pr13/delivery_race.py` (a barrier before each thread's second lane entry): on `a414804` the result was `{1: ok, 0: RuntimeError storage validation}`. Fixed in the follow-up commit: the first-callback branch also calls `_check_not_applied`, right after `self._require(...)`. Test: `test_two_first_callbacks_that_both_pass_the_relookup_record_once`, with exactly that interleaving. It failed red first (`[receipt, RuntimeError('Case state failed storage validation')]`) and now passes. M5 is therefore backed by a repro. `delivery_race.py` on the fix gives `{1: ok, 0: ok deduplicated}` with one transition. |
| I1 | K2 was understated. Beyond the 5-minute model proposal expiry, there is a worse path: a channel-triggered refresh at +31 min yields a proposal that expires at +36, and the next refresh at +61 min comes after the offer expired at +60, so no approval is possible for the rest of the offer. | Documented as a known limit, model Slow only (decision 17 keeps Slow scripted in every authorized flow), with the re-consult trigger still deferred. It is recorded in `docs/architecture.md` (standing-proposal paragraph) and in the spec's K2 risk row. |
| M1 | At consumption the offer is matched by id only, with no revision check. | The `standing_proposal_offer` docstring now states the precondition: a Runtime Case holds exactly one deterministic offer whose revision never changes, which the codec enforces, and the A-3 check bound the revision at admission. A Runtime with revisable offers must also check the revision. |
| M2 | Spec table: rule 6 was listed against the executor's `capability_proposal_not_current`, but rule 6 is a lower bound and the executor's check is an upper bound. | The spec table is corrected. The spec now also says that no rule mirrors `approval_required`, and why that is safe: the model's intent never reaches the snapshot, `_build_approval` compiles the Runtime's own, the contract forces `approval_required=True` for an accept, and the executor requires an approval for an approval-required action. |
| M3 | `SLOW_PROPOSAL_CHECK_VERSION` is not stamped on traces. | Recorded as a limit in the log. `ModelTrace` has no field for it, and adding one is a contract change, which is outside PR-13. |
| M4 | No test covered an A-3 rejection at a refresh on the append and channel paths. | Added `test_an_a3_rejected_refresh_fails_the_command_and_keeps_the_state[append\|channel]`, taken from `refresh_reject.py`. It checks four things: the command fails as `slow`; the snapshot and standing proposal are unchanged; the last trace is the Slow `REJECTED` with `slow_proposal_capability_action_mismatch` and `slow_proposal_action_not_delegated`; and on the channel path the inbox stays reserved. `refresh_reject.py` gives the same result on the branch. |
| M6 | `ScriptedProposingSlowAdapter` proposes without checking delegation. | Its docstring now says this is unreachable today: every Runtime Case makes the accept approval-required. For a Case that did not, the accept intent would fail contract validation and the Slow call would raise; an undelegated action that reached admission would be rejected as a whole by rule 11. |

## Verification

The checks after these changes are recorded in
`harness/log/feat-pr13-slow-drives-intent.md` ("Review follow-up" and
"Re-review follow-up"). The re-review confirmed B1 on the append and ingest
paths and found the first-callback gap above, which is now fixed.

The DB lane has not run on this branch yet: `postgres-check`,
`phase05a-check` and `phase06b1-check` are all still to do. The
`/security-review` scan has not run either.
