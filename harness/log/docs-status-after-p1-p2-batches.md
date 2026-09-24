# Docs log: audit-remediation status after P1 close and the first P2 batches

Branch `docs/status-after-p1-p2-batches` from `origin/main` @ `74e2073`.
Docs only; one file changed besides this log:
`harness/context/audit-remediation-status.md`.

## What changed

- Header: updated 2026-09-24, `main` @ `74e2073`.
- §0 rewritten: no work in flight (#72–#78 merged, no open PR, the three
  remaining remote branches belong to the merged #44, #46, #71). Resume
  order: rest of P2 (batch plan pending), the §4a backlog (R-2, R-5, R-6,
  R-11…R-18), then the proposal stages with decision 15 and the Phase 03C
  next-phase choice asked first. Added the working mode (subagents implement,
  check and review; root decides, reviews final diffs, merges; `git merge
  origin/main` over rebase, no force-push). Gate-hygiene paragraph kept.
- §1: P1 done (#72); P2 row and the latest recorded gate updated (#77 and #78
  each gated on `8e1522a`; no gate recorded on the combined tip).
- §3: the PR4 row closed with #72 and the root's clock decision.
- §4: new closed table (A-7d/e/g, G-1 documented only, the three programme
  items, D3-7 + D2-6, B1-6/7/8/10/11, E-7…E-10); #74's limits listed; the
  open list trimmed accordingly.
- §4a: closed table (R-10, R-1/R-1b, R-3, R-8); the pre-fix designs replaced
  by spec pointers, rejected alternatives kept (the R-1 spec cites them);
  R-15 updated; R-16, R-17, R-18 added.

## Evidence checked

- `git log --oneline -12 origin/main`: #72 `f818b61`, #73 `c914c1b`, #74
  `0735f9c`, #75 `14d3fcf`, #76 `8e1522a`, #77 `bd8451c`, #78 `74e2073`.
- `git show --stat` of each: logs `feat-persisted-claim-and-traces.md`,
  `docs-p2-reconciliation.md`, `fix-p2-ml-eval-hygiene.md`,
  `fix-r10-terminal-delivery-callback.md`, `fix-p2-adapter-domain.md`,
  `fix-p2-web-hygiene.md`, `fix-r1-retryable-update-continues-as-new.md`.
- #73's programme items: `docs/development.md` lines 49–67, 96–103;
  `tests/contract/test_phase_03a1_hosted_rerun_architecture.py` lines 37–49.
- R-15 on #75: GitHub Actions run 35961699413, attempt 1, job
  107511471085 (`phase-gate`): `assert 21 <= 20`; attempt 2 succeeded.

## Checks

- Passed: `git diff --check` (exit 0).
- Passed: `make preflight-fast` (exit 0; layout validation, `compileall`,
  diff checks).
- Not run: `make lint`, `make test`, `make preflight` (markdown only; no code,
  test or artifact changed).
