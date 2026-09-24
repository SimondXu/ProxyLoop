# Fix: gate honesty (R-15 flaky ceiling test, G-1 strong form)

Build-plan PR-1, run under the 2026-09-22 standing authorization. Branch
`fix/gate-honesty-r15-g1` from `origin/main` @ `e1c8371`.

## R-15

`ml/tests/test_teacher_pipeline.py::test_concurrent_workers_cannot_jointly_exceed_the_ceiling`
asserted `8 <= calls <= 20` and saw 21 on CI (#71; #75 run 35961699413
attempt 1) while `total_estimated_usd <= ceiling` and `reserved_usd == 0`
held. Task: decide whether 20 is a real invariant of `TeacherLedger`.

- If 21 is reachable with the invariants holding: make the concurrency
  deterministic in the test, assert the true invariant, keep "concurrent
  workers never jointly exceed the ceiling" fully tested.
- If 21 violates a real invariant: write a failing deterministic regression
  and stop for a root decision before touching the ledger.
- Do not touch `_R4_EXECUTION_PATHS` modules or committed `data/`.
- Evidence: the test run at least 200 times.

## G-1 strong form

`make preflight` exits 0 while silently skipping the DB/Temporal-gated tests.
Make it honest without failing locally or in CI (which runs `make preflight`
without `PROXYLOOP_TEST_*`): at the end of preflight print the gated-skip
count and name `postgres-check`, `phase05a-check`, `phase06b1-check`; pin the
expected count so a test newly skipping, or a gated test disappearing, fails
preflight with a clear message. Structured mechanism, not log grepping.
Update `docs/development.md` ("Local gate and real-dependency gates") and the
`CLAUDE.md` gate bullet; do not grow `AGENTS.md` (12000-byte cap).

## Non-goals

No ledger or pipeline source change, no DB gates, no `PROXYLOOP_TEST_*`, no PR.
