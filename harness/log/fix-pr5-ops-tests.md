# Fix log: ops and test findings C-5, C-7, C-8, R-6 (PR-5)

Findings: `harness/code_review/repo-audit-C.md` C-5, C-7, C-8;
`harness/context/audit-remediation-status.md` §4a R-6 (origin:
`harness/log/fix-capability-manifest-lifetime.md`, Known limits). Plan row:
`harness/context/build-plan-to-complete.md` PR-5.
Branch `fix/pr5-ops-tests` from `main` @ `74fb993`; merged with `main` @
`f4a2487` (#90) after review.

Hot-file constraint for this PR: no edits to `runtime.py`,
`postgres_repository.py` (PR-7), `app.py` or `workflow.py` (PR-3). None were
edited.

## Validity on `main` @ `74fb993`

| Id | Verdict | Evidence |
|---|---|---|
| C-5 | still valid | `scripts/run_phase_07a_portfolio_demo.py:786-790` raises "already has a process state" inside the `try`; the `finally` at `:835` unlinked `pids.json` unconditionally; host services start with `start_new_session=True` (`:564`) and survive the crashed supervisor |
| C-7 | still valid | `tests/integration/test_phase_04c_persistent_case_store.py:165-175` compared seven fields; `CaseRuntimeState` (`case_runtime/repository.py:28-50`) has eleven non-Provider fields. Omitted: `transitions`, `last_fast_decision` (as reported) and also `execution_claim`, `model_traces` (not named in the finding) |
| C-8 | partly fixed | #75 (R-10) added `test_postgres_delivery_callback_after_complete_is_stored` (`test_phase_06b1_channel_runtime.py:811`), one real-PostgreSQL happy path on a COMPLETE Case. Still uncovered on real PostgreSQL: the callback on an in-progress Case, the transaction rollback of `replace_with_delivery_receipt` (`postgres_repository.py:741-878`), and the prior-receipt (duplicate) and regression branches |
| R-6 | still valid; **deferred** (see below) | The Provider fixes `expires_at = issued_at + 1 h` (`provider_simulator/provider.py:114`); `runtime.py:742` constructs `FictionalMobileProvider()` with no seam; `postgres_repository.py:1176-1182` reconstructs the Provider with `FictionalMobileProvider()` and requires the regenerated offer to equal the stored one. Persisted Cases keep the manifest they were minted with (no migration; A-11 known limit) |

## What changed

- **C-5** `scripts/run_phase_07a_portfolio_demo.py` `start_demo`: the
  `finally` unlinks `pids.json` only when this invocation spawned the host
  services (`processes` is non-empty; `_spawn_host_services` writes the file
  only after every service started). A refused start keeps another
  supervisor's file, so `make portfolio-demo-stop` can still find and stop
  those processes. Stop-file and lifecycle-lock handling are unchanged.
  `docs/portfolio-demo.md` gains one troubleshooting note: delete
  `$TMPDIR/proxyloop-portfolio-demo/pids.json` by hand if a stale file names
  PIDs that now belong to other processes (stop refuses to signal them).
- **C-7** `_assert_non_provider_fields_equal` iterates
  `dataclasses.fields(CaseRuntimeState)` minus `provider`, so it compares all
  eleven non-Provider fields and any field added later. The three DB-gated
  call sites (`postgres-check`) now also compare `transitions`,
  `last_fast_decision`, `execution_claim`, `model_traces`; each compares two
  reads of the same row or a no-write repeat. A DB-free test,
  `test_every_non_provider_field_survives_the_postgres_codec`, sends a
  waiting and an executed terminal in-memory state (both reached through
  commands, so `transitions` and `last_fast_decision` are populated) through
  `_encode_state` → JSON → `_decode_state` and compares with the helper.
- **C-8** `tests/integration/test_phase_06b1_channel_runtime.py`, two
  real-PostgreSQL tests (gated on `PROXYLOOP_TEST_DATABASE_URL`, run by
  `make phase06b1-check`):
  - `test_postgres_delivery_callback_write_is_atomic_and_retryable`: an
    in-progress Case with an accepted outbound reply; a subclass
    (`_InboxWriteFailureRepository`) points the final Inbox write of one
    callback at a missing row, so the Case UPDATE, Outbox UPDATE and receipt
    INSERT have run when the transaction raises `CaseConflictError`. Asserts
    nothing persisted (snapshot, transitions, Outbox `accepted`, Inbox
    `reserved`, zero receipt rows); the identical command then applies once
    (revision +1, one `provider_event` Evidence whose id the receipt
    carries, Outbox `delivered`, Inbox `applied`, one receipt row).
  - `test_postgres_repeated_delivery_callback_keeps_one_receipt`: a second
    `delivered` callback for the same delivery takes the prior-receipt path.
    It is not a no-op: the snapshot, revision and the one receipt are kept,
    but it records its transition, marks its Inbox `applied`, and rewrites
    the Outbox with the same state. A `bounced` callback is then refused by
    the Runtime (`runtime.py:565`, `ChannelConflictError` "regressed") before
    storage, so the test also calls `replace_with_delivery_receipt` directly:
    an Outbox regression `delivered` → `bounced`
    (`postgres_repository.py:781-784`) and a receipt differing from the
    stored one (`:801-802`) both raise "delivery observation regressed" and
    write nothing (snapshot, transitions, Outbox `delivered`, that Inbox
    `reserved`, the one receipt).
- No product code outside the demo script changed.

## Red → green

| Test | Pre-fix | Post-fix |
|---|---|---|
| `test_phase_07a_portfolio_demo.py::test_refused_start_keeps_the_process_state_of_a_crashed_supervisor` (stale `lifecycle.lock` owned by an exited PID plus `pids.json`, the real second-start path) | FAILED on the `74fb993` script: `_read_pids` raised "portfolio demo is not running" (the refused start deleted `pids.json`) | passed; 07A file 16 passed |
| `test_phase_04c_persistent_case_store.py::test_round_trip_helper_compares_every_non_provider_field[transitions, last_fast_decision]` (DB-free) | 2 FAILED: `DID NOT RAISE AssertionError` | 2 passed |
| `test_every_non_provider_field_survives_the_postgres_codec` (DB-free) | not applicable: pins existing codec behaviour | passed; 04C file 7 passed, 23 skipped (DB) |
| the two C-8 tests | not applicable: coverage of existing behaviour, not a defect | skipped locally (no DB); **unrun** until the DB lane runs `make phase06b1-check` |

## Known limits

- C-5, pre-dating this PR (`_spawn_host_services`,
  `run_phase_07a_portfolio_demo.py:556-579`), host services can still be
  orphaned without a `pids.json` that names them: a SIGINT/SIGTERM during
  the spawn loop (the handler raises out of `start_demo` before the file is
  written, and `processes` in `start_demo` is still empty); a `write_text`
  failure at `:574` (the services are running, the exception propagates,
  nothing terminates them); and a SIGKILL of the supervisor before `:574`.
  Not changed here.
- C-8: the `prior_receipt is None` branch for a terminal Outbox
  (`postgres_repository.py:803-807`) stays without real-PostgreSQL coverage;
  no API path produces a `delivered`/`bounced` Outbox without a receipt.
- C-8: PR-7 may change the `replace_with_delivery_receipt` signature; if it
  does, `_InboxWriteFailureRepository` (and the direct calls in the
  repeated-callback test) must follow.

## R-6 deferred until after PR-7

An injectable offer TTL that a runtime test can use needs a constructor seam
in `runtime.py` (the only `create_case` Provider construction, `:742`), and a
PostgreSQL round trip of such a Case needs `postgres_repository.py`
(`_reconstruct_provider` regenerates the offer with the default TTL and
would reject a 48 h offer as "stored offer does not match the deterministic
Provider"). Both files belong to PR-7. Monkeypatching the module global
`runtime.FictionalMobileProvider` in a test would avoid the edit but is not
a seam and leaves the persisted path failing, so it was not done.

Proposed seam (for the root to decide; the storage part is a
security-relevant choice):

1. `provider.py`: `FictionalMobileProvider(*, offer_ttl: timedelta =
   timedelta(hours=1))`, refusing a non-positive TTL; `issue_offer` uses it.
   Default output is byte-identical.
2. `runtime.py`: `ThinAgentRuntime(..., offer_ttl: timedelta =
   timedelta(hours=1))`, passed to the Provider in `create_case`. Refuse at
   `create_case` a TTL that would put `offer.expires_at` past
   `case.goal.deadline`, instead of letting `_build_approval`'s manifest
   guard raise after the Fast decision (A-11 review Minor 4).
3. `postgres_repository.py` `_reconstruct_provider`: either (a) derive the
   TTL from the stored offer (`expires_at - created_at`) — simplest, but the
   deterministic regeneration then no longer detects a tampered
   `expires_at`; or (b) persist the TTL in the Provider configuration
   (`provider_config_ref` or an envelope field) — keeps tamper detection,
   needs a storage decision (PR-7 bumps `storage_version` to 3 anyway).
   Recommendation: (b).

Test plan:

- in-memory: `offer_ttl=48 h`, create at T, approval at T+1 min, approve at
  T+25 h → COMPLETE, `execution_count == 1`, one `confirmation` Evidence;
- counter-control: default 1 h TTL, approve at T+25 h → refused as expired
  (pin the exact error when writing the test), no execution;
- `offer_ttl` past the Case deadline → refused at `create_case`, no write;
- `postgres-check`: the 48 h Case round-trips through `get` after a fresh
  repository construction; a stored offer with a tampered `expires_at` is
  rejected (option (b)).

The "persisted Cases keep their 1-day manifest" half of R-6 stays an
accepted known limit (no migration; A-11 log).

## Gated-skip count

The two C-8 tests are gated on `PROXYLOOP_TEST_DATABASE_URL`. After merging
`main` @ `f4a2487`, `make preflight` failed only at the #90 pin
(`test_phase_06b1_channel_runtime.py: expected 1, found 3`; total 53 → 55).
`EXPECTED_GATED_SKIPS_PER_FILE` in `scripts/check_gated_skips.py` and the
list in `docs/development.md` now say 3 (total 55).

## Checks

First pass (on `74fb993`): `make lint`, `make typecheck`, `make test` exit 0;
`make preflight` exit 2 at `format-check` (the C-7 helper's `assert` line),
exit 0 after `ruff format`.

After review and the `f4a2487` merge, no `PROXYLOOP_TEST_*` set:

- `make preflight`: exit 2 at the gated-skip pin (above); after the pin
  update, exit 0 (runtime 1288 passed, 55 skipped; ML 397 passed,
  1 skipped; web 140 passed; "Gated-skip counts match the pinned 55 per
  file.").
- `make lint`: exit 0. `make typecheck`: exit 0 (67 and 59 source files,
  no issues). `make test`: exit 0 (runtime 1288 passed, 55 skipped; ML 397
  passed, 1 skipped). Run after the last code change; only the log, status
  and review-artifact text changed after `make preflight`.
- Not run (lane held): `make postgres-check` (C-7 call sites),
  `make phase06b1-check` (the two C-8 tests).
