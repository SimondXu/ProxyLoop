# Feature log: PR-10, the Agent Status Bar (Stage 4)

Spec: `harness/context/pr10-agent-status-bar-preflight.md`, written first on this
branch and amended after the review. Inputs: build plan row PR-10;
`audit-remediation-status.md` §5 item 4; PR-8 I12. Branch
`feat/pr10-agent-status-bar` from `origin/main` @ `c018390` (#95).

## What changed

- `apps/web/lib/status-block.ts` (new): the pure
  `renderStatusBlock(payload, { blocked })` returns `{ doingNow, asOf, rows }`.
  The rows are Phase, Goal, Constraints, Current offer, Approval, Execution, and
  Completion, in a fixed order. It reads only allow-listed projection fields, reads
  no clock, and never reads `fast`. It is the only place the Status Bar's text is
  built.
- `apps/web/lib/runtime-client.ts`: `phaseForPayload` moved here from the
  workspace and is now the single classifier for the workspace and the bar. Its
  behaviour did not change.
- `apps/web/lib/format.ts` (new): `formatMoney`, moved from the workspace, and
  `formatMoneyOrNull`.
- `apps/web/app/components/conversation-workspace.tsx`: `AgentStatusBar` is the
  first context-rail section. It uses `aria-labelledby` and receives
  `blocked={phase === "blocked"}`. It adds no text of its own.
- `apps/web/app/globals.css`: two `.agent-status` rules put each label above its
  value and wrap long values.
- `tests/contract/test_status_block_boundary.py` (new): the I12 tripwire. The gate
  imports only stdlib and `proxyloop_contracts`. No source under any
  `runtime/*/*/src` or `ml/` names a status-block renderer. Every scanned root is
  non-empty.
- Docs: the `docs/architecture.md` Experience Layer; the
  `audit-remediation-status.md` §0 row and §5 item 4; the review record
  `harness/code_review/feat-pr10-agent-status-bar.md`.

No API, projection, contract, runtime, or committed-artifact change. No
DB-gated test was added, so the gated-skip pin is unchanged at 63.

## Red → green

- First pass, red on `c018390`: `lib/status-block.test.ts` failed to import
  (`Failed to resolve import "./status-block"`). The workspace case failed with
  `Unable to find role "region" and name "Agent status"`.
- First-pass mutation checks. Adding `import proxyloop_agent_core.status_block`
  and a `render_status_block` comment to `disclosure_gate.py` failed both Python
  tests. Adding a `p.fast` reader to `status-block.ts` failed the source test.
  Both files were restored.
- Review follow-up (I-1..I-3 and the Minors), run against the renderer as it was at
  `aed0978`:
  - 14 cases failed: the unverified completion, rejected, candidate_complete and
    closed phase lines, both invalid-pending variants, approved/not pending/not
    done, terminal candidate_complete, the Blocked option, finalizing with a
    pending or null decision, as-of revision, the empty-decision fallback, and the
    unnamed Provider.
  - The workspace "PR-10 I-1" case failed with `blocked={false}`.
- Green: vitest 187 passed (156 on `main`, plus 29 in `status-block.test.ts` and
  2 in the workspace).

## Checks

- `make web-check` exit 0: lint, typecheck, vitest 187 passed, `next build`.
- `make preflight` on `081109b` exit 0. Runtime pytest reported 1470 passed and
  63 skipped, and the gated-skip count matches the pin. ML pytest reported 397
  passed and 1 skipped. Every committed `*-check` passed. The first rerun after the
  review failed on ruff RUF005 in the new boundary test; that was fixed in
  `081109b`.
- Not run: the DB gates. No service code changed. No `PROXYLOOP_TEST_*` variable
  was set.

## Browser evidence

Headless Chromium via Python Playwright 1.54, at a 1440x1000 viewport, against
the real durable Runtime. Readiness reported
`{"ready":true,"adapter_mode":"scripted","storage_mode":"postgres","orchestration_mode":"temporal"}`.
The Web was the production build of `081109b` (`next start`).

- Setup deviated from `make portfolio-demo` but used the same components. Port 8000
  is held by an unrelated process (PID 78583/84230), which was not touched. The
  throwaway Compose project `proxyloop-pr10-browser` ran with postgres on 55463 and
  temporal on 7264 on a fresh volume. The scratch launcher ran the supervisor's
  worker, Runtime, and Web commands with its environment and no model credentials:
  Runtime on 8011, Web on 3011. Playwright forwarded `/api/runtime/**` to 8011.
  Afterwards only those processes were stopped and the project was removed with
  `down -v`. The existing `proxyloop-*` containers, `proxyloop_postgres-data`, and
  `proxyloop-portfolio-demo_postgres-data` are unchanged.
- The flow was intake $92 / $75 / yes / yes, then Create, then Keep both unchanged,
  then Approve, then reload. Runtime calls: `POST /cases`, `GET`, `POST .../events`,
  `GET`, `POST .../approvals/{id}`, `GET`, and after the reload `GET /health/ready`
  and `GET`. The console had no errors or warnings.
- What the Status Bar showed at each stage:
  - After create: "Planning from your confirmed goal.", as of Case revision 2,
    phase Strategy, approval None, execution Not started, completion "Not Done ·
    Approval Or Execution Pending". The Goal row showed the target, the bill, and
    the Runtime's deadline. The offer row showed the Runtime's offer.
  - After confirm: "Waiting for your approval of the exact terms.", revision 4,
    phase Awaiting Approval, "Pending · expires 2026-09-24T15:01:25.265824Z". This
    is the same expiry the approval card shows.
  - After approve (read 150 ms after the click) and at completion: "Done: the
    Runtime verified completion against Provider Evidence.", revision 6, phase
    Complete, approval Approved, "Executed 1 time", "Verified complete · 1
    matching Evidence ID · receipt shown". The receipt artifact was shown.
  - After reload (durable restore): identical rows.
- The approval POST returned after execution, so the finalizing state was not
  observable in this run. It is covered by the vitest cases only.
- The offer row shows the Runtime's offer verbatim: `pine-mobile`, $72.00/month,
  total $864.00, no fees, 0 months. The Offer artifact also shows "0 months". This
  is Runtime data, not a Status Bar defect.
- Screenshots (scratch, not committed), in `.../scratchpad/impl-pr10/browser/`:
  `01-after-create.png`, `02-after-confirm-pending-approval.png`,
  `03-after-approve.png`, `04-completion-verified-receipt.png`, and
  `05-after-reload.png`. The bar text per stage is in `result.json`.

## Limits

- The Status Bar does not show channel delivery status or the Fast gate verdict,
  because neither is projected. "Delivery" is shown as execution status (the root
  accepted this). It shows no compliance verdict and does not rank offers; the
  "Current offer" wording was also accepted.
- Expiry is shown verbatim as ISO, with no countdown. The workspace's local
  deadline timer can disable Approve before the Runtime expires the approval. In
  that window the bar still shows the Runtime's "Pending · expires …" and the
  approval line until an authoritative read reports `expired`.
- While a command is in flight, the bar shows the last accepted payload, marked
  "as of Case revision N".
- The context rail, and so the Status Bar, is hidden below 1120 px. This is
  existing rail behaviour.
- `audit-remediation-status.md` §1 still says "Proposal stages … not started". That
  line was stale before this PR and was left unchanged.
