# Fix: Web surfaces failure instead of silence (P0-8)

Bounded repository change approved by the user on 2026-09-21 (Group 1).
Branch `fix/web-failure-surfacing` from `main` after P0-3 merges. Resolves
audit findings **E-1, E-2, E-3** (Important); see
`harness/code_review/repo-audit-E.md` and
`docs/research/2026-09-21-repository-audit.md` §6 P0 row 8.

## Defects (observed on main)

- E-1 `apps/web/app/components/conversation-workspace.tsx:1046-1053,
  1107-1114`: on a 409 from the event or approval POST the component reads
  the Case and returns without `setError`; if the read did not advance the
  revision the UI returns to `confirm`/`approval`, `busy` clears, the button
  re-enables, and the stale pending command is kept (`pendingResolved`,
  `:663`). Nothing is shown. With runtime B2-3 this repeats forever.
- E-2 `:938-950`: Finalizing polling stops after 5 reads (`pollCount >= 5`
  → `return`) with no state change; the reconnect control renders only
  when `error !== null` (`:1247`); the Progress artifact keeps "Waiting for
  the authoritative response."
- E-3 `:660-666`: `pendingResolved` treats a `decide_approval` command as
  resolved as soon as `approval.decision !== "pending"`, but the runtime
  writes `approved + pending_execution=true` before executing
  (`runtime.py` claim write), so the stored exact retry is discarded
  precisely when the P0-1 recovery path needs it.

## Frozen design

All in `apps/web/app/components/conversation-workspace.tsx` unless noted.

1. **409 reconciliation (E-1).** In both catch blocks, after
   `readAuthoritativeCase(...)` resolves, compare the revision before and
   after the read. If it did not advance: `setError(statusMessage(category))`
   where `category = errorCategory(caught)` from `runtime-client.ts` (add
   copy for `model_result_rejected` → "The Runtime refused this turn
   (category: model_result_rejected). Reconnect and read the Case, or
   restart the demo." and for `case_conflict` → "The Case moved while this
   request was in flight. I read the current state; retry if the action is
   still offered."), keep the phase the read produced, and **clear the
   stale pending command** (`clearPendingCommand()` or set it to `null`
   in storage) so restore does not replay it. If the read advanced the
   revision, current behaviour (silent adopt) stays.
2. **Poll exhaustion (E-2).** When `pollCount.current >= 5` in the
   `restoring | working | finalizing` poll effect, do not return silently:
   `setError("Still waiting for the authoritative result after 5 reads.
   The Runtime may have an execution in progress or stuck; reconnect to
   read the Case again.")` once (guard with a ref so it fires one time),
   leaving the phase unchanged. The existing `RuntimeErrorState` then
   renders "Reconnect and read Case"; a successful reconnect resets
   `pollCount` and clears the error.
3. **Pending approval retry (E-3).** In `pendingResolved`, the
   `decide_approval` branch returns `true` only when
   `next.snapshot.pending_execution !== true && (next.approval?.decision
   !== "pending" || completionHasVerifiedEvidence(next))`; mirror the
   `append_event` branch. `restorePersisted` then re-issues the exact
   stored command (same key, same body) while `pending_execution` is true,
   which the runtime (P0-1) now completes.
4. `docs/ui/state-matrix.md`: update row 13 (Finalizing: bounded polling →
   explicit "still pending" error with reconnect) and row 18 (Error: 409
   after event/approval now shows the category) so the doc matches the
   implementation. No other docs.

## Out of scope

`runtime-client.ts` beyond the two `statusMessage` entries; `app.py`;
direct-mode behaviour (E-4, B2-4); the "blocked" re-offer (E-5) and the
missing test inventory (E-6) except the tests below; intake parsing
(E-10); layout/CSS.

## Regression tests (write first; each must fail on the pre-fix code)

In `apps/web/app/components/conversation-workspace.test.tsx`, using the
existing mock harness (the lane's probes R1–R3 under the session
scratchpad `laneE/laneE.repro.tsx` show the exact mock shapes):

- **R1 inverted**: `appendConsumerEvent` rejects
  `RuntimeClientError(..., "http", 409, "model_result_rejected")` and
  `getCase` resolves the unchanged payload → a `role="alert"` with the
  category text is rendered, the confirm button is disabled or absent
  until reconnect, and `loadPersistedWorkspace().pendingCommand` is `null`.
- **R2 inverted**: `getCase` returns a fresh `pending_execution: true`
  payload every call → after the 5th read the "still waiting" error and
  the "Reconnect and read Case" button are rendered, exactly 5 GETs made
  before the error, and clicking reconnect issues a 6th read.
- **R3 inverted**: persisted `decide_approval` command with durable
  readiness; `getCase` returns `approved + pending_execution: true` →
  `decideApproval` is called once with the stored key and body; the
  pending command is cleared only after a payload with
  `pending_execution: false` and verified evidence.
- **Unchanged**: the existing 47 tests pass unmodified (if one encodes the
  silent behaviour, STOP and report which).

## Verification

`pnpm --filter @proxyloop/web test`, `pnpm --filter @proxyloop/web
typecheck`, `pnpm --filter @proxyloop/web lint`, `make web-check`
(includes the production build). Root runs `make preflight` once.

## Escalate instead of deciding

Any change to the Runtime API contract or `runtime-client.ts` validation
predicates; any existing test whose assertion must flip; any need to
change `next.config.ts` or the rewrite.
