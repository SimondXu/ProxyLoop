# Fix log: gate honesty (R-15, G-1 strong form)

Spec: `harness/context/fix-gate-honesty-r15-g1-preflight.md`.
Branch `fix/gate-honesty-r15-g1` from `origin/main` @ `e1c8371`.

## R-15 diagnosis

Not a ledger bug; `calls <= 20` was a guess. Numbers for this test
(`claude-sonnet-5`, 3/15 USD per M, `max_output_tokens` 512):
`per_call` p = 0.0063; worst cases over the 40 rows range from
w_min = 0.015645 to W = 0.016077 (2.48p to 2.55p); ceiling
C = 20p + W - 1e-9 = 0.142077 (22.55p).

- Upper bound (reservation rule): when the last call was admitted, every
  other call was settled (p) or still reserved (w >= p), so
  `(calls - 1) * p + w_min <= C`, i.e. calls <= 21. The ceiling alone would
  allow 22.
- Lower bound: the refused reservation saw at most 7 other in-flight worst
  cases, each of which still became a call, so
  `(calls - 7) * p + 8 * W > C`, i.e. calls >= 10.
- 21 is reachable even sequentially: after 20 calls the 11th prompt's worst
  case (below W) still fits (simulated in scratch, concurrency 1: 21 calls).
  The old comment "no more calls than the sequential twenty" was wrong.

## What changed

- `ml/tests/test_teacher_pipeline.py`: new `_FirstWaveCompletions` fake; the
  first 8 calls wait at a `threading.Barrier(8, timeout=10)` whose action
  snapshots the ledger and asks it to `reserve` the cheapest worst case. The
  test asserts: nothing settled, `reserved == sum of the first eight worst
  cases <= ceiling`, the ninth reservation refused; then the derived bounds
  above instead of `8 <= calls <= 20`. Later calls take 10 ms so workers keep
  overlapping. No source change.
- `scripts/check_gated_skips.py` (stdlib only): parses the runtime pytest
  JUnit (xunit1, for the `file` attribute) report, counts skips whose message
  contains `PROXYLOOP_TEST_`, prints them per file, names the three
  real-dependency targets, and fails unless the count equals
  `EXPECTED_GATED_SKIPS = 51`. A missing report fails. With any non-empty
  `PROXYLOOP_TEST_*` set the pin is reported, not enforced.
- `Makefile`: `unit-test` runtime pytest adds
  `-o junit_family=xunit1 --junitxml=.gate/runtime-junit.xml`; `preflight`
  ends with `python3 scripts/check_gated_skips.py`; the script is in the
  runtime ruff and mypy lists. `.gitignore`: `.gate/`.
- `tests/contract/test_gated_skips_check.py`: 5 tests (per-file count
  ignoring other skips, pinned pass naming the targets, count +/-1 fails,
  missing report fails, pin not enforced with a variable set, empty variable
  counts as unset).
- Docs: `docs/development.md` (make-target table, gate section: five gated
  files with counts, the mechanism), `CLAUDE.md` gate bullet,
  `harness/context/audit-remediation-status.md` (R-15 and G-1 strong form
  closed on this branch).
- Finding: a fifth gated file, `test_phase_06b1_channel_runtime.py` (1 test,
  skipped through a fixture imported from `test_phase_06b1_temporal.py`),
  was missing from the docs list; `phase06b1-check` already runs it.

## Evidence

- R-15, 200 fresh pytest processes of the test: `passed=200 failed=0`
  (ran concurrently with the distribution run below, so under CPU load).
  An earlier loop was stopped and discarded: it ran while the file was being
  edited and its 6 failures were half-applied edits (`too many values to
  unpack`).
- Distribution, 200 in-process runs: final test 13 calls in all 200; without
  the 10 ms tail delay 21 in all 200 (so the old `<= 20` fails
  deterministically against an instant fake).
- Mutation: `would_exceed` ignoring `reserved_usd` -> the final test fails
  (`assert True is False`, the ninth reservation admitted); file restored.
  Without the barrier probe this mutation passed, which is why the probe
  exists.
- G-1 output after `make test` (exit 0):

  ```
  Gated tests skipped for a missing PROXYLOOP_TEST_* variable: 51
    tests/integration/test_phase_04c_persistent_case_store.py: 23
    tests/integration/test_phase_05a_case_runtime.py: 2
    tests/integration/test_phase_05a_temporal_workflow.py: 22
    tests/integration/test_phase_06b1_channel_runtime.py: 1
    tests/integration/test_phase_06b1_temporal.py: 3
  Skipped gated tests are covered only by the real-dependency gates: make postgres-check, make phase05a-check, make phase06b1-check (docs/development.md, "Local gate and real-dependency gates").
  Gated-skip count matches the pinned 51.
  ```

- `make format-check lint typecheck`: exit 0 (ruff clean; mypy no issues in
  67 and 59 source files).
- `make preflight-fast`: exit 0.
- `make test` (after `pnpm install --frozen-lockfile`): exit 0; runtime 1228
  passed, 51 skipped; ml 397 passed, 1 skipped.

## Verification after merging `main` @ `c73f6a7` (#82–#86)

- Merge: one conflict, `harness/context/audit-remediation-status.md`
  (four hunks); kept `main`'s text and re-applied this branch's changes
  (R-15 and G-1 strong form closed, R-2 row kept alongside the R-15 row).
- `make preflight` (no `PROXYLOOP_TEST_*` set): exit 0. Runtime 1256
  passed, 51 skipped; ml 397 passed, 1 skipped; web 140 passed; ruff and
  mypy clean. It ends with the gated-skip output above, unchanged: `main`'s
  new tests (#82, #85) add no gated skips, so the pin stays 51.
- R-15, 200 fresh pytest processes of the test (sequential, no other load):
  `passed=200 failed=0`.

## Review and root decisions

Independent review: Approve (`harness/code_review/fix-gate-honesty-r15-g1.md`).
Root decisions, applied on this branch:

- `scripts/check_gated_skips.py`: only `PROXYLOOP_TEST_DATABASE_URL` and
  `PROXYLOOP_TEST_TEMPORAL_ADDRESS` decide enforcement (other
  `PROXYLOOP_TEST_*` names are ignored). Neither set: pin enforced. Both
  set: 0 gated skips required. Exactly one set: report only.
- The pin is per file (`EXPECTED_GATED_SKIPS_PER_FILE`; the total is its
  sum), so a deleted gated test plus an unrelated new gated skip no longer
  cancel out. A failure lists each file whose count differs.
- Wording: "removed or renamed" became "removed, added, or moved between
  files" (a rename does not change the count) in the script and
  `docs/development.md`; the `CLAUDE.md` gate bullet states the
  enforcement rule.
- `tests/contract/test_gated_skips_check.py`: 9 tests; new cases cover an
  unknown variable ignored, both set with 0 skips passing, both set with
  skips failing, one set report-only (each variable), a per-file mismatch
  with the same total failing. Red first: the new tests failed to import
  `EXPECTED_GATED_SKIPS_PER_FILE` before the script change.
- Recorded limit (review Minor 4): a break of the R-15 barrier surfaces as
  a provider failure, so the test still fails, but indirectly.
- Follow-up (review Minor 5): the real-dependency gates do not themselves
  require 0 gated skips; added to the open list in
  `harness/context/audit-remediation-status.md`.

Checks after the change (no `PROXYLOOP_TEST_*` set, no DB/Temporal):
`make lint` exit 0; `make typecheck` exit 0; `make test` exit 0; `make
preflight` exit 0 with runtime 1260 passed, 51 skipped; ml 397 passed, 1
skipped; web 140 passed; last line `Gated-skip counts match the pinned 51
per file.`

Merge order is PR-4 -> PR-2 -> PR-1.

## Pin update after merging `main` @ `5266b6d` (#87, PR-2)

- Merge: one conflict in `harness/context/audit-remediation-status.md`
  (two hunks): kept `main`'s PR-2 row and R-16 bullet next to this
  branch's PR-1 row; the R-15 "flaky" bullet stays removed (closed here).
- `make preflight` then failed as intended: `FAIL: expected 51 gated
  skips, found 53`, `test_phase_05a_temporal_workflow.py: expected 22,
  found 24`. Cause: #87 parametrized two gated tests,
  `test_time_skipping_expiry_retry_exhaustion_keeps_workflow_alive` and
  `test_time_skipping_non_retryable_expiry_failure_does_not_spin`, as
  `[unchained]`/`[chained]` (+1 each). Its other new tests run without the
  variables.
- Pin updated: `test_phase_04c_persistent_case_store.py` 23,
  `test_phase_05a_case_runtime.py` 2, `test_phase_05a_temporal_workflow.py`
  24, `test_phase_06b1_channel_runtime.py` 1, `test_phase_06b1_temporal.py`
  3; total 53. `docs/development.md` list and count updated.
- `make preflight` rerun: exit 0; runtime 1269 passed, 53 skipped; ml 397
  passed, 1 skipped; web 140 passed; ruff and mypy clean; last line
  `Gated-skip counts match the pinned 53 per file.`

## Not run / remaining

- No DB/Temporal gates run (none needed; no service code changed).
- No PR opened (not requested).

## Notes

- xunit1 is pytest's legacy JUnit family, used only for the per-test `file`
  attribute (xunit2 reports an empty `classname` for tests outside the
  `runtime/` rootdir).
