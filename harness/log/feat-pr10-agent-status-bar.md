# Feature log: PR-10, the Agent Status Bar (Stage 4)

Spec: `harness/context/pr10-agent-status-bar-preflight.md` (written first on this
branch). Build plan row PR-10; `audit-remediation-status.md` §5 item 4; PR-8 I12.
Branch `feat/pr10-agent-status-bar` from `origin/main` @ `c018390` (#95).

## What changed

- `apps/web/lib/status-block.ts` (new): pure `renderStatusBlock(payload)` →
  `{ doingNow, rows }`, where the rows are Phase, Goal, Constraints, Current offer,
  Approval, Execution, and Completion in a fixed order. It reads only allow-listed
  projection fields and no clock, and it never reads `fast`. It is the only place
  the Status Bar's text is built.
- `apps/web/app/components/conversation-workspace.tsx`: `AgentStatusBar` is the first
  section of the context rail (`aria-label="Agent status"`), shown once an accepted
  payload exists. It maps the rows to `dt`/`dd` and adds no text of its own. No
  other artifact, phase rule, or fetch changed.
- `apps/web/app/globals.css`: two rules stack each label above its value and wrap
  long values (`.agent-status`).
- `tests/contract/test_status_block_boundary.py` (new, I12): the disclosure gate
  imports only the standard library and `proxyloop_contracts`. No Python source
  under `agent_core/src`, `openai_adapter/src`, or `ml/` names `status_block`,
  `render_status_block`, `status-block`, or `renderStatusBlock`.
- Docs: the `docs/architecture.md` Experience Layer; the §0 row and §5 item 4 in
  `audit-remediation-status.md`.

No API, projection, contract, runtime, or committed-artifact change. No
DB-gated test was added, so the gated-skip pin is unchanged.

## Red → green

- Red on `c018390`: `lib/status-block.test.ts` failed to import (`Failed to resolve
  import "./status-block"`). The new workspace case failed with `Unable to find role
  "region" and name "Agent status"` inside the context rail.
- Green: `pnpm exec vitest run` passed all 176 tests (156 before, plus 19 in
  `status-block.test.ts` and 1 workspace case).
- The Python boundary test passes on `main` as well, because it pins today's
  state. A mutation check showed both tests catch violations. Appending `import
  proxyloop_agent_core.status_block` and a `render_status_block` comment to
  `disclosure_gate.py` made both Python tests fail. Appending a function that reads
  `p.fast` to `status-block.ts` made the source test fail. Both files were restored.

## Checks

See the root report for the final `make web-check` and `make preflight` results
on the pushed sha.

## Limits

- The Status Bar does not show channel delivery status or the Fast gate verdict,
  because neither is projected. "Delivery" is shown as execution status. It shows
  no compliance verdict and does not rank offers.
- Expiry is shown verbatim as ISO, with no countdown.
- The context rail, and therefore the Status Bar, is hidden below 1120 px. This is
  existing rail behaviour.
- `audit-remediation-status.md` §1 still says "Proposal stages … not started". That
  line was stale before this PR (8a/8b) and was left unchanged.
