# PR-10 Agent Status Bar review

**Target**: `feat/pr10-agent-status-bar` @ `aed0978` against `main` @ `c018390`
(spec `harness/context/pr10-agent-status-bar-preflight.md`).

**Reviewer**: independent read-only `reviewer` subagent, with a scratch probe
(`rev-pr10/probe.ts`) run against the renderer.

**Recommendation**: Request Changes. There is no Blocking finding. The three
Important findings are all cases where the Status Bar disagreed with the rest of
the Web. The root accepted every finding and the Minors listed below, and passed
them to the implementer, who wrote this file from the root's messages. The root
also accepted the spec's two interpretations as recorded limits: "Current offer"
instead of "best current offer", and execution status instead of delivery status.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| I-1 | The bar kept describing an active state after the workspace went Blocked, including on a stale payload held after a rejected read. It also described states the workspace itself Blocks: an invalid pending approval, approved + not pending + not done, and a terminal `candidate_complete` ("checking…"). | Applied. `phaseForPayload` moved into `apps/web/lib/runtime-client.ts` as the single pure classifier used by both the workspace and `renderStatusBlock`. The workspace passes its Blocked state (`renderStatusBlock(payload, { blocked })`). A blocked classification or a Blocked workspace renders "Stopped — state not verified. Reconnect or restart the local demo." Tests: renderer, both invalid-pending variants (no hash, unparseable expiry); approved/not pending/not done; terminal candidate_complete (asserts no "checking" claim; the old phase-mapping test was fixed); `blocked: true` on a valid approval payload. Workspace "PR-10 I-1": after an approval POST whose authoritative read drifts, the bar reads Stopped, "as of Case revision 4", with no approval wording. The workspace test fails with `blocked={false}`. |
| I-2 | "Executing the approved fictional transition" was shown for any pending execution. The Progress artifact names an approval only when `approval.decision === "approved"` (M-4). | Applied: same condition. A pending or null decision reads "Finalizing the fictional transition; waiting for a verified result." Tests for both. |
| I-3 | The Python boundary test scanned a fixed list of roots. | Applied. It now scans every `runtime/*/*/src` plus `ml/`, asserts each root has Python sources and that the Fast-side seams are among them, and keeps the structural check that the gate imports only stdlib + contracts. `docs/architecture.md` now says I12 is enforced by placement, because Python cannot import the TS renderer; the test is a tripwire. |
| m | The "doing now" line goes stale during non-blocked errors. | Applied: the block carries "as of Case revision N". |
| m | An empty decision string rendered a blank `dd`. | Applied: "Not reported" for approval and completion. |
| m | Missing-Provider wording differed from the offer card. | Applied: "Fictional Provider". |
| m | `formatMoney` was copied into the renderer. | Applied: shared `apps/web/lib/format.ts` (`formatMoney`, `formatMoneyOrNull`) is used by the workspace and the renderer. |
| m | The Web importer test missed dynamic `import(...)`. | Applied. |
| m | The section should use `aria-labelledby`. | Applied (`agent-status-title`). |
| m | The workspace's local-clock deadline window is not described. | Recorded as a limit in the spec amendment and the log. |

## Verification after the follow-up

- Red: 14 of the new or changed renderer cases fail against the pre-review renderer
  (`aed0978`), and the workspace I-1 case fails when the Blocked state is not
  passed.
- `make web-check`: exit 0, vitest 187 passed.
- `make preflight` on `081109b`: exit 0 (runtime 1470 passed / 63 skipped, pin
  matches; ML 397 passed / 1 skipped).
- Browser check against the real durable Runtime at every stage: after create,
  after confirm (pending approval with its expiry), after approve, at completion
  with the verified receipt, and after reload.

Evidence: `harness/log/feat-pr10-agent-status-bar.md`.

## Re-review

**Target**: `feat/pr10-agent-status-bar` @ `06d3b46`. **Result**: all four checks
(I-1, I-2, I-3, the Minors) pass. One narrow Important finding remains, and the root
accepted it:

| # | Finding | Disposition |
|---|---|---|
| R-1 | After create the Runtime sits in `strategy`, waiting for the consumer (the workspace shows "Needs input" and the confirm button), but the bar said "Planning from your confirmed goal." (Browser screenshot 01). | Applied. The workspace passes `awaitingConsumer: phase === "confirm"` next to `blocked`, and the line reads "Waiting for you to confirm the Task Brief." `blocked` still wins. "Planning…" now shows only while the confirmation command runs (`working`). Red first: the renderer case and the workspace PR-10 case failed (2 failed / 187 passed). Green: vitest 189 passed. The workspace case holds the event POST open on a deferred promise and checks for "Planning" only while it is in flight. |

Screenshot 01 was not retaken. The lane was already released and the throwaway
Compose project removed, and the vitest cases cover the change.
