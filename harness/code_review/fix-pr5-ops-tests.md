# PR-5 ops and test findings (C-5, C-7, C-8; R-6 deferred) Independent Review

**Date**: 2026-09-24
**Branch**: `fix/pr5-ops-tests` (build-plan item PR-5)
**Reviewer**: independent read-only `reviewer`
**Recommendation**: Approve, conditional on the DB gates (`make postgres-check`,
`make phase06b1-check`) passing

## Scope reviewed

- C-5: `start_demo`'s `finally` in `scripts/run_phase_07a_portfolio_demo.py`
  and its test in `tests/integration/test_phase_07a_portfolio_demo.py`;
- C-7: `_assert_non_provider_fields_equal` and its self-test in
  `tests/integration/test_phase_04c_persistent_case_store.py`;
- C-8: the two real-PostgreSQL delivery-callback tests in
  `tests/integration/test_phase_06b1_channel_runtime.py`;
- R-6: the deferral, the proposed seam and the test plan in
  `harness/log/fix-pr5-ops-tests.md`.

The reviewer reproduced C-5 on the pre-fix script with a stale lifecycle lock
(`red_c5.py`) and ran the C-7 helper over the PostgreSQL codec without a
database (`sim_c7.py`).

## Findings and disposition

This records the Minors as the root relayed them, with the implementer's
disposition.

| Finding | Disposition |
| --- | --- |
| Minor 1: the `bounced` callback is refused by the Runtime (`runtime.py:568`) before storage, so the SQL regression checks in `replace_with_delivery_receipt` (`postgres_repository.py:781-784`, `:801-807`) have no real-PostgreSQL coverage. The repeated-callback docstring called the duplicate a no-op, but it adds a transition, marks its Inbox applied and rewrites the Outbox. | Fixed. The test now calls `repository.replace_with_delivery_receipt` directly twice: an Outbox regression (`delivered` → `bounced`, `:781-784`) and a receipt that differs from the stored one (`:801-802`); both raise "delivery observation regressed", and the test asserts nothing was written (snapshot, transitions, Outbox `delivered`, that Inbox `reserved`, the one receipt). The docstring states what the repeat does; the test also asserts the added transition. The `prior_receipt is None` branch (`:803-807`) stays uncovered: it needs a terminal Outbox without a receipt, which no API path produces. Log and status wording corrected. |
| Minor 2: orphan paths that pre-date this PR in `_spawn_host_services` (`:556-579`) are not recorded. | Recorded as known limits in the log. |
| Minor 3: no operator guidance when a stale `pids.json` names PIDs now owned by other processes. | Fixed: one troubleshooting note in `docs/portfolio-demo.md`. |
| Minor 4: the C-5 test did not exercise the real second-start path (a crashed supervisor also leaves its lifecycle lock). | Fixed: the test leaves `lifecycle.lock` owned by an exited PID; still red on the pre-fix script (`_read_pids` raises "portfolio demo is not running"), green after, and it asserts the reclaimed lock is released. |
| Minor 5: nothing DB-free pins that every non-Provider field survives the codec. | Fixed: `test_every_non_provider_field_survives_the_postgres_codec` sends a waiting and an executed terminal in-memory state through `_encode_state` → JSON → `_decode_state` and compares with the helper. |
| Minor 6: PR-7 may change the `replace_with_delivery_receipt` signature. | Recorded in the log: `_InboxWriteFailureRepository` must follow. |

## Verification after the fixes

Merged `main` @ `f4a2487` (#90's per-file gated-skip pin). No
`PROXYLOOP_TEST_*` set, no DB/Temporal: `make preflight` first failed only
at the pin (`test_phase_06b1_channel_runtime.py: expected 1, found 3`); the
pin and `docs/development.md` were updated to 3 (total 55), then `make
preflight`, `make lint`, `make typecheck`, `make test` all exit 0 (numbers in
the log). The C-8 tests and the stricter C-7 call sites are unrun until the
DB lane runs `make postgres-check` and `make phase06b1-check`.
