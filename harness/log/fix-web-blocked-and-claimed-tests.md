# Fix log: a blocked response never re-offers confirm; the recorded Web tests exist (P1 E-5, E-6)

Spec: `harness/context/fix-web-blocked-and-claimed-tests-preflight.md`.
Resolves audit findings E-5 and E-6 (Important) from
`harness/code_review/repo-audit-E.md`. Branch
`fix/web-blocked-and-claimed-tests` from `main` @ `1e55982`.

## What changed

- `apps/web/app/components/conversation-workspace.tsx` (E-5)
  - Component-local `BlockedStateError` (a `RuntimeClientError`, kind
    `invalid`) marks a response the Web classifies as blocked.
  - Blocked is sticky (root decision 5). `enterBlocked(message)` sets a
    `blockedRef`, `phase = "blocked"` and the error. It is the only place
    besides `holdBlocked` that sets `blocked`. Only `restart()` and
    `reconnect()` clear `blockedRef`.
  - `readAuthoritativeCase` does three things after the session check:
    - If `blockedRef` is set, it throws `BlockedStateError` without accepting
      the payload or changing phase. This stops an in-flight GET issued before
      blocked from moving the phase.
    - If `hasValidTaskBrief` fails, or `phaseForPayload` returns `blocked`, it
      calls `enterBlocked` and throws.
    - A stale read (lower revision or cursor) keeps the old non-blocking
      error, so a late poll still cannot regress the UI.
  - The direct `hasValidTaskBrief` checks on the create, event and approval
    responses throw `BlockedStateError`. The create check was added after root
    decision 1 below.
  - `holdBlocked(caught)` runs in the catch blocks of `confirmConstraint`,
    `approveExactTerms`, `loadCase` and `restorePersisted`. It enters
    `blocked` for a `BlockedStateError`, keeps `blocked` if `blockedRef` is
    already set, and returns true either way, so the caller stops. The 409
    reconcile read is skipped once blocked.
  - Other errors, when not blocked, still fall back to `confirm`, `approval`
    or `intake`. Network, 503 and malformed responses stay retryable with the
    exact stored command.
  - `confirmConstraint` and `approveExactTerms` return early when
    `blockedRef` is set.
  - The working/finalizing and deadline poll timers return early once
    blocked. Their catches and the approve-deadline catch no longer overwrite
    the blocked error.
  - In `blocked`, the Task Brief's disabled primary button reads "Blocked".
    Before, it read "Constraint confirmed". The only ways out are an explicit
    "Reconnect and read Case" (when a locator is stored) or "Restart local
    demo". A late POST failure, an in-flight GET, or a poll cannot leave
    `blocked`; B1, I2b and M2 pin this.
- `apps/web/lib/runtime-client.ts`: unchanged.
- Tests: `conversation-workspace.test.tsx` gains R6, R7, B1 (event and
  approval), I1, I2a, I2b, M2, sticky I1–I3 and 25 E-6 cases. `runtime-client.test.ts`
  gains 7 E-6 cases. The 52 pre-existing tests are unchanged.

## Red → green

| Test | `main` component | First-pass diff (non-sticky) | Final |
|---|---|---|---|
| R6 incomplete pending approval read back (M1: unconditional disabled + "Blocked" text) | fail: enabled `Keep both unchanged and continue` | pass | pass |
| R6 event response drifts an intake fact | fail: same | pass | pass |
| R7 create response mismatches the confirmed draft | fail: `Create fictional Case` re-offered | fail (before decision 1) | pass |
| B1 working poll blocks, then the event POST fails with a network error | fail | **fail: after the rejection "Blocked" is gone (fell back to `confirm`)** | pass |
| B1 twin: deadline poll blocks during approve, then the approval fails | fail | **fail: after the rejection "Blocked" is gone (fell back to `approval`)** | pass |
| I1 approval response drifts an intake fact | fail | pass | pass |
| I2a valid event response, drifted Case read | fail | pass | pass |
| I2b finalizing poll reads an incomplete approval → progress gone, polling stops | fail | pass | pass |
| M2 reconnect from blocked with the Case still blocked → no POST replayed | fail (no "Blocked" label on `main`; its POST-count assertions alone would hold) | pass | pass |

The `main` column comes from running the test file (before sticky I1–I3
were added) with `main`'s component swapped in and restored afterwards: 9
failed (exactly the rows above), 60 passed. Every E-6 test passed on `main`.

### Sticky pins (re-review) and mutations

Each mutation was applied to the final component and the full suite run.
The component was then restored from a backup, and `cmp` confirmed it was
identical.

| Test | Mutation | Result under mutation |
|---|---|---|
| sticky I1: a poll blocks, then the in-flight event POST returns a valid pending approval and later reads are valid → still Blocked, no approval | N7: remove the `if (blockedRef.current) throw` guard at the top of `readAuthoritativeCase` | only sticky I1 fails (1 of 96) |
| sticky I2: blocked → Reconnect reads a valid Case → Approve clickable, a double click sends exactly one `decideApproval`, no duplicate event | N8: remove `blockedRef.current = false` in `reconnect` | only sticky I2 fails (1 of 96) |
| sticky I3: blocked → Restart → a fresh intake reaches a clickable confirm | N9: remove `blockedRef.current = false` in `restart` | only sticky I3 fails (1 of 96) |

- Defence in depth, not pinned by tests. Removing these guards has no
  observable effect, because the sticky `blocked` phase already stops the
  poll effects from scheduling and the buttons from calling their handlers:
  - the `blockedRef` early returns in the working/finalizing and deadline
    poll timers;
  - the entry guards in `confirmConstraint` and `approveExactTerms`;
  - the `!blockedRef.current` skip of the 409 reconcile read in both action
    catches.
- `restorePersisted`'s catch changed from a plain `setPhase("blocked")` to
  sticky `enterBlocked`. Observable behaviour is unchanged: that path already
  showed Blocked and offered Reconnect, and Reconnect clears the flag and
  recovers (sticky I2, M2).

## Root decisions (2026-09-23)

1. The create-response mismatch in `loadCase` goes to `blocked` too, per the
   state-matrix row "Malformed Task Brief → Blocked". Implemented with
   regression R7.
2. A blocked workspace keeps its stored pending command. "Reconnect and read
   Case" reads first. If the Case has since become valid and the command is
   still unresolved, reconnect replays the exact stored command with the same
   key. This is the 06A recovery path, not a new event. No change.
3. The claim of "a fresh polling budget per semantic command" stays covered
   only indirectly, through `resetPollBudget()` at confirm and approve entry.
   No test isolates it, because any phase change also resets the budget. No
   change.
4. E-10 (USD edge cases such as `$92.` and `$1,50`) stays out of scope. No
   change.
5. After review: blocked is sticky. Once any path sets `blocked`, only an
   explicit Reconnect or Restart leaves it.

## E-6 claims now pinned

| Claim (source) | Test | Result |
|---|---|---|
| Strict USD rejects (intake-ux:122-123) | `rejects the non-strict USD input %s locally` × 12 (`12.345`, `$12.345`, `-5`, `-$5`, `$-5`, `1e3`, `$1e3`, `$`, `€92`, `92 EUR`, `£92`, `$92 or $95`); `cannot submit an empty USD input` | passed immediately |
| `temporal_unavailable` copy (06A review:36-39, AC 11) | client `maps HTTP 503 …` × 2 (with and without code); UI `keeps the exact event retry and truthful copy on temporal_unavailable` | passed immediately |
| Readiness `ready:false` (06A rule 3) | client `returns ready:false with the Temporal category …`; UI `preserves the saved Case and pending command when readiness reports ready:false` | passed immediately |
| Direct readiness profile (06A AC 5) | client `reports the direct readiness profile …`; UI `makes no recovery claim against a non-durable readiness profile` × 3. Each case changes exactly one field of the durable profile: no `orchestration_mode`, `storage_mode: memory`, or a non-scripted `adapter_mode` (M4). | passed immediately |
| 404 / 422 (06A rule 3, AC 14) | client `maps HTTP 404/422/409 …`; UI `shows the bounded reset message and invents no Case on a restore 404`, `shows no Task Brief when create is rejected with 422` | passed immediately |
| Restore-409 message (06A command rules) | `discards a stale restored command with the restore-409 message` | passed immediately |
| Double-click suppression (06A AC 8) | `suppresses a double click on confirm …`, `suppresses a double click on approve` | passed immediately |
| Blocked / Connecting / Working labels (state-matrix) | Blocked: R6 and restore 404; Connecting: `shows Connecting while …`; Working: the confirm double-click test | passed immediately |
| Deadline backoff and polling budget (06A review:36-39) | `backs deadline reads off to 1500 ms and stops after the 5-read budget`. The finalizing budget was already pinned by R2 in `fix-web-failure-surfacing`. | passed immediately |

Mutation checks on the deadline test, each reverted afterwards: raising the
budget from 5 to 50 fails it ("called 6 times, but got 16"). Setting the
backoff from 1500 ms to 0 fails it ("called 2 times, but got 3").

## Review

- The first independent review (`reviewer`) returned **Request Changes**.
- B1 (Blocking) was the race: a poll blocked the workspace, then the late
  POST failure fell back to `confirm` or `approval`. Fixed with sticky
  `blockedRef`, pinned by the two B1 tests.
- I1 asked for approval-side R6 coverage. Fixed with I1.
- I2 asked for coverage of a drifted Case read after a valid event, and of a
  finalizing poll that blocks. Fixed with I2a and I2b, which also assert that
  polling stops.
- M1: R6 now asserts unconditionally that `#task-brief-confirm` is disabled
  and reads "Blocked". Fixed.
- M2: reconnect from blocked replays no POST. Fixed with M2.
- M3: the log's "only ways out" statement now matches the sticky semantics.
  Fixed.
- M4: each direct-profile case now differs from the durable profile in one
  field. Done.
- Re-review: code behaviour correct; **Request Changes** because three tests
  were missing. They are added as sticky I1, I2 and I3, from the reviewer's
  scenarios. The probe file was not present in the scratch copy, so the
  tests were written from the scenario descriptions. Mutations N7, N8 and N9
  each kill exactly one of them. No code change.

## Checks

- Passed: `pnpm install --frozen-lockfile`. This worktree had no
  `node_modules`, so we installed from the lockfile with no lockfile change.
- Passed: `make web-check`, exit 0: lint, `tsc --noEmit`, vitest with 2 files
  and 93 tests, and `next build`. This run followed the review fixes.
- Passed: `make preflight-fast`, exit 0. This run followed the review fixes.
- Root, final diff: `make preflight` exit 0 — runtime 705 passed / 42 gated
  skips, ML 374 passed / 1 skipped, web 96 passed. Re-review of the sticky
  fix: code correct; three missing tests added (each kills its mutation).
- Not run: the real-dependency gates (no API/runtime change) and a Browser
  smoke pass.
