# Local conversation intake UX review

Date: 2026-08-25

Reviewer: fresh independent Terra, read-only

## Review target

Complete working-tree diff on `feat/local-conversation-intake-ux` against
`main@0d0acb3`, reviewed against
`harness/build/phase-local-conversation-intake-ux.md`. Root
`task_plan.md`, `findings.md`, and `progress.md` are excluded planning scratch.

## Initial recommendation

`REQUEST_CHANGES`

No P0 finding. Terra reported:

1. **P1 — contradictory financing language**: the `no change(s)` shortcut
   could accept a sentence that later requested a financing change.
2. **P1 — validation evidence**: durable final evidence was not yet appended;
   the finding also statically estimated test counts that contradicted actual
   captured runner output.
3. **P2 — event stale response**: create and approval restart races had tests,
   but the event await guard did not.
4. **P2 — UI documentation**: the state matrix promised a Retry action that
   the blocked UI does not expose.

## Sol disposition and remediation

- Accepted the parser issue. Financing `no change(s)` now confirms only when
  the remaining answer has no contrary negative/change/allow meaning. The exact
  contradictory sentence stays local, keeps create disabled, and has a
  regression test.
- Accepted the durable evidence gap. Exact commands and outputs are recorded in
  the phase preflight and append-only build log. `pytest --collect-only`
  independently reports `45/46 collected (1 deselected)`; actual Vitest output
  reports `27 passed` after the two new review regressions.
- Accepted the event race gap. A deferred event response resolved after New
  task cannot restore a Task Brief, Approval, or receipt.
- Accepted the docs mismatch. The matrix now offers only the implemented page
  refresh or local-demo restart.

Post-remediation focused and full verification passed. The detailed command,
Browser, cleanup, and scope evidence is recorded in
`harness/context/phase-local-conversation-intake-preflight.md`.

## Final rereview

The first rereview confirmed the evidence, event-race, and documentation
findings resolved, but returned `REQUEST_CHANGES` for one remaining P1: the
negative-synonym check could miss the contradictory verb `modify` after a
`no change` prefix.

The same implementer replaced financing free-text detection with a normalized
whole-answer allowlist and added Terra's exact sentence as a fail-closed
regression. Web checks reported `2 files / 28 tests`; full preflight reported
Runtime `201`, ML `177`, Web `28`, and all gates passed. Browser also confirmed
the exact sentence left create disabled with no verified Task Brief and no
console warning/error.

The second rereview confirmed the preceding findings resolved but returned
`REQUEST_CHANGES` for one analogous P1: hotspot confirmation still used a
free-text positive match and could accept `yes, remove mobile hotspot`.
The same implementer moved both fixed booleans to normalized whole-answer
allowlists and added that exact fail-closed regression. Final Web checks report
`2 files / 29 tests`; final full preflight reports Runtime `201`, ML `177`, Web
`29`, and all gates passed. In-app Browser verification of the exact hotspot
sentence kept create disabled, left the hotspot fact missing, displayed only a
local alert, exposed no verified Task Brief, and emitted no console
warning/error.

## Final recommendation

`APPROVE_PHASE_GATE`

The same Terra reviewer inspected the current complete diff after the hotspot
remediation and found no P0, P1, or P2 findings. The reviewer confirmed both
fixed booleans use normalized whole-answer allowlists, the exact hotspot and
financing contradictions stay local, and the API, canonical Case, drift,
approval, Evidence, completion, and stale-response boundaries retain the
previously reviewed semantics.

The reviewer did not rerun commands or Browser in this final pass. The
recommendation relies on source/test inspection plus Sol's captured final
Runtime `201`, ML `177`, Web `29`, full-preflight, and Browser evidence. It is
an independent local phase-gate recommendation, not a PR, CI, merge, or
closeout claim.
