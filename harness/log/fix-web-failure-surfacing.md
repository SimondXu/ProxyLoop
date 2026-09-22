# Fix log: Web surfaces failure instead of silence (P0-8)

Spec: `harness/context/fix-web-failure-surfacing-preflight.md`. Resolves
audit findings E-1, E-2, E-3 (Important). Branch `fix/web-failure-surfacing`
from `main` @ `fadc665`.

## What changed

- `apps/web/app/components/conversation-workspace.tsx`
  - E-1: both 409 catch blocks (constraint event, approval) compare the
    revision the request was made against with the revision the reconcile
    read returned. Not advanced → `clearPending(command)`,
    `setStaleRetryDropped(true)`, `setError(caught.message)` (the client's
    `statusMessage(category)`); the phase the read produced is kept.
    Advanced → silent adopt as before.
  - New state `staleRetryDropped`: gates the primary action only after an
    E-1 drop. `TaskBriefArtifact` gets `blockedLabel` and `ApprovalArtifact`
    gets `blocked`, both rendering "Reconnect to continue" instead of the
    misleading "Constraint confirmed" / "Sending exact approval…". A
    transient non-409 failure keeps the button and the stored exact retry
    (same idempotency key). `clearFailure()` replaces the five
    `setError(null)` sites and resets the flag.
  - E-2: the `restoring | working | finalizing` poll effect reports
    "Still waiting for the authoritative result after 5 reads…" once
    (`pollBudgetExhaustedReported` ref, reset by `resetPollBudget()` which
    replaced the six `pollCount.current = 0` sites); `RuntimeErrorState`
    then offers "Reconnect and read Case".
  - E-3: `pendingResolved` for `decide_approval` requires
    `pending_execution !== true`, so the stored exact retry survives the
    runtime's `approved + pending_execution=true` claim write (P0-1) and
    `restorePersisted` replays it with the stored key and body.
- `apps/web/lib/runtime-client.ts`: two `statusMessage` entries only —
  `model_result_rejected` split out with copy naming the category;
  `case_conflict` copy updated.
- `docs/ui/state-matrix.md`: Finalizing row (bounded polling now reports
  "still waiting" with reconnect) and HTTP-failure row (non-advancing 409
  shows the category message, drops the stale retry, primary action reads
  "Reconnect to continue").
- Tests `apps/web/app/components/conversation-workspace.test.tsx`: R1
  (409 `model_result_rejected`, unchanged read → alert, disabled button
  labelled "Reconnect to continue", `pendingCommand === null`, reconnect
  restores the button without re-sending the event), R2 (five
  `pending_execution` reads → still-waiting alert + reconnect, exactly 5
  GETs before the error, reconnect reads again and replays the pending
  event with the same key), R3 (persisted `decide_approval`,
  `approved + pending_execution:true` → `decideApproval` called once with
  the stored key/body, cleared only after `pending_execution:false` +
  verified evidence), plus the transient non-409 retry test added after
  review. The 47 pre-existing tests are unchanged.

## Red → green

| Test | Pre-fix (`main` component + client) | Post-fix |
|---|---|---|
| R1 | `Unable to find role="alert"` | pass |
| R2 | `Unable to find … role "alert"` (5 GETs then silence) | pass |
| R3 | `expected [] to have a length of 1` (`decideApproval` never called) | pass |

Reviewer re-ran the new test file against `main`'s sources in a scratch
copy: 3 failed / 47 passed.

## Checks

- Passed: `pnpm --filter @proxyloop/web test` 51; `typecheck`; `lint`;
  `make web-check` (production build).
- Passed: `make preflight` on the stable diff — runtime 316 / 39 gated
  skips, ML 279, web 51, all artifact gates valid.
- Independent review (`reviewer`, Opus): first pass **Request Changes** —
  I-1 the root's `error === null` gate blocked button retry after any
  transient failure (fatal in direct mode where reconnect and restart are
  both unavailable, E-4); I-2 the disabled buttons showed "Constraint
  confirmed" / "Sending exact approval…" while an error was displayed.
  Root replaced the gate with `staleRetryDropped` + honest labels and
  added the transient-failure test. Re-review **Approve**: I-1 no longer
  holds, labels truthful, the flag is cleared on every successful-read
  entry (`restorePersisted`, `loadCase`, restart, confirm/approve start).
  Root decisions confirmed by the reviewer: clearing the pending command
  on a non-advancing 409 loses no runtime-completable retry (the P0-1
  same-command retry requires the claim write, which advances the
  revision and takes the silent-adopt branch); the E-2 one-shot guard
  re-fires only after `resetPollBudget()`.

## Known limits (reviewer minors, not fixed here)

- `case_conflict` copy says "retry if the action is still offered" while
  the confirm action needs a reconnect first (copy frozen in the spec).
- The two `statusMessage` copy entries have no test in
  `runtime-client.test.ts` (R1 constructs the error message by hand).
- The E-2 error is not auto-cleared if a replay in flight later advances
  the Case to a receipt (`readAuthoritativeCase` never clears errors);
  unlikely under the scripted runtime.
- Direct mode (no Temporal) still cannot recover after an E-1 drop
  because reconnect requires the durable profile (E-4, out of scope).
- `blockedLabel` is passed whenever `staleRetryDropped`, so a TaskBrief
  rendered on the `expired` phase after an approval-side E-1 reads
  "Reconnect to continue" (practically unreachable).
