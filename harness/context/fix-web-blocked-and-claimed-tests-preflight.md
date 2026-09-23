# Fix: a blocked response never re-offers confirm; the recorded Web tests exist (P1 E-5, E-6)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Branch `fix/web-blocked-and-claimed-tests` from `main` (after #57, the
browser projection allow-list).

## Defects (audit `harness/code_review/repo-audit-E.md` §E-5, §E-6)

**E-5 (Important).** In `apps/web/app/components/conversation-workspace.tsx`,
`readAuthoritativeCase` (~:675-687) accepts the payload before the `blocked`
check and throws; `confirmConstraint`'s catch (~:1054) sets
`phase = "confirm"`, so `TaskBriefArtifact` renders with `onConfirm` enabled
and "Needs input", and clicking sends another `POST /events`. The docs promise
fail-closed: `phase-minimal-local-web-demo.md:38-39` ("never expose a confirm
or approval action"), `state-matrix.md:15`. The existing test
(`conversation-workspace.test.tsx:343`) asserts only that the approval
button is absent. Reachability today: a projection the Web predicates reject.

**E-6 (Important).** Tests recorded as present do not exist:
`phase-local-conversation-intake-ux.md:122-123` requires strict USD parsing
tests; `harness/code_review/phase-06a-durable-web-resume.md:36-39` states the
Temporal-unavailable copy, deadline backoff and polling budget "each … has
focused coverage"; 06A AC 5/14 require direct-mode and 404/422 coverage.
Grep finds no rejected USD input, no `temporal_unavailable` string, no
`ready:false`, no non-Temporal readiness profile, no 404/422, no restore-409
message, no double-click suppression, no "Blocked"/"Connecting"/"Working"
label; `runtime-client.test.ts:73-80` checks 409/503 by `kind`/`status` only.

## Frozen design

1. **E-5**: a response the Web classifies as `blocked` (predicates reject
   the projection, or the runtime reports a blocked/terminal category) moves
   the workspace to a terminal `blocked` state that renders **no** confirm
   and **no** approval action, shows the "Blocked" label/copy the state
   matrix defines, and sends no further `POST /events` or approval POST from
   that state. The only way out is the existing reconnect/reload path (if the
   state matrix defines one) — do not invent a new flow. Fix the catch in
   `confirmConstraint` (and any sibling handler with the same pattern) so an
   error after a blocked classification cannot fall back to `confirm`.
2. **E-6**: write the missing tests against the **current** behaviour, one
   per claim, in the existing test files (`runtime-client.test.ts`,
   `conversation-workspace.test.tsx`). If a claimed behaviour does not
   actually exist or is wrong, do NOT silently weaken the claim: fix it if
   the fix is small and clearly specified by the cited doc; otherwise stop
   and report it to root with the doc line and the observed behaviour.
3. No API/runtime change. No visual redesign.

## Regression tests (write first)

- **R6 / E-5 (fails on main)**: drive the component with a blocked
  projection during constraint confirmation → assert no confirm button, no
  approval button, the blocked label visible, and exactly one `POST /events`
  was sent (a second click has nothing to click).
- **E-6 list**: rejected USD inputs (e.g. `12.345`, `-5`, `1e3`, `$`, empty,
  non-USD symbol) per the intake doc; Temporal-unavailable copy
  (`temporal_unavailable`); readiness `ready:false`; a non-Temporal (direct)
  readiness profile; 404 and 422 handling; the restore-409 message;
  double-click suppression on confirm and approve; the "Blocked",
  "Connecting", "Working" labels; deadline backoff and polling budget.

## Verification

`make web-check` (lint, tsc, vitest, build); `make preflight-fast`.
