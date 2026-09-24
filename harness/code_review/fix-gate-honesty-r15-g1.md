# Fix gate honesty (R-15, G-1 strong form) Independent Review

**Date**: 2026-09-24
**Branch**: `fix/gate-honesty-r15-g1` (build-plan item PR-1)
**Reviewer**: independent read-only `reviewer`
**Recommendation**: Approve

## Scope reviewed

- R-15: the derived bounds `10 <= calls <= 21` and the barrier probe in
  `ml/tests/test_teacher_pipeline.py::test_concurrent_workers_cannot_jointly_exceed_the_ceiling`;
- G-1 strong form: `scripts/check_gated_skips.py`, the `unit-test` JUnit
  report and the `preflight` step in the `Makefile`,
  `tests/contract/test_gated_skips_check.py`, and the gate text in
  `docs/development.md` and `CLAUDE.md`.

## Findings and disposition

This records the findings as the root relayed them with its decisions.

| Finding | Disposition |
| --- | --- |
| Any non-empty `PROXYLOOP_TEST_*` name turned enforcement off, including names the gated tests never read. | Fixed. Only `PROXYLOOP_TEST_DATABASE_URL` and `PROXYLOOP_TEST_TEMPORAL_ADDRESS` decide enforcement: neither set enforces the pin, both set require 0 gated skips, exactly one set reports only. |
| A total-only pin lets a deleted gated test and an unrelated new gated skip cancel out. | Fixed. The pin is per file (`EXPECTED_GATED_SKIPS_PER_FILE`; the total is its sum); a failure lists each differing file. |
| "removed or renamed" was wrong: a rename does not change the count. | Fixed in the script message and `docs/development.md`: "removed, added, or moved between files". |
| The `CLAUDE.md` gate bullet did not state when the pin is enforced. | Fixed: the bullet states the two-variable rule. |
| Minor 4: a break of the R-15 barrier surfaces as a provider failure, so the test still fails, but indirectly. | Recorded limit (`harness/log/fix-gate-honesty-r15-g1.md`). |
| Minor 5: the real-dependency gates do not themselves require 0 gated skips. | Follow-up, on the open list in `harness/context/audit-remediation-status.md`. |

New tests in `tests/contract/test_gated_skips_check.py`: an unknown variable
is ignored; both variables set with 0 skips passes and with skips fails;
exactly one set is report-only; a per-file mismatch with the same total
fails.

## Verification after the fixes

No `PROXYLOOP_TEST_*` set, no DB/Temporal: `make lint`, `make typecheck`,
`make test`, `make preflight` all exit 0; preflight ends with `Gated-skip
counts match the pinned 51 per file.` The R-15 test passed 200/200 in fresh
processes after merging `main` @ `c73f6a7`. Real-dependency gates were not
run (no service code changed).
