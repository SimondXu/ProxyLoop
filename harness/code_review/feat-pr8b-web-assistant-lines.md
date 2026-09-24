# PR-8b Web assistant lines review

**Target**: `feat/pr8b-web-assistant-lines` @ `c402055` against `main` @ `5266b6d`
(spec `pr8-fast-dialogue-design.md` §4.3, §6.2 I10, §6.3 AC 7, §6.4 Web).

**Reviewer**: independent read-only `reviewer` subagent.

**Recommendation**: Approve with Minors. No blocking finding. The root
accepted M1–M4 and set M5's disposition, and passed them to the implementer,
who wrote this file from the root's messages.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| M1 | `assistantLines` did not dedupe cursors, so a repeated cursor would render twice under one React key. | Applied: it keeps the first well-formed entry per cursor. Tests: client "keeps the first well-formed entry for a repeated cursor"; workspace "8b M1" (one bubble, no React "same key" warning). |
| M2 | A 600-character line with no spaces could widen the bubble and break the three-column grid. | Applied: `overflow-wrap: anywhere` on `.message-bubble` in `apps/web/app/globals.css`. No vitest case (jsdom does no layout); covered by the pending Browser check. |
| M3 | Missing tests for Case isolation and stale-poll rollback. | Applied: workspace "8b M3a" (Case A's line is gone after New task and after Case B is created) and "8b M3b" (a lower-revision poll read, then a same-revision lower-cursor read, both without the line, leave it shown). |
| M4 | Lines render as one group after the Task Brief, not interleaved with consumer turns by cursor. | No code change: recorded in the log's Limits. Ordering must interleave by cursor once PR-13 brings multi-turn Web dialogue. |
| M5 | `harness/context/audit-remediation-status.md` is edited by several concurrent PRs, so a merge conflict is likely when this branch merges. | No change; resolved at merge time by keeping both sides. |

## Verification after the follow-up

- Scratch mutation check: without the dedupe, both M1 tests fail; with
  `acceptPayload`'s stale guards removed, M3b fails.
- `make web-check`: exit 0, vitest 156 passed.
- `make preflight`: exit 0.
- Pending: Browser check on `make portfolio-demo` after 8a merges (the line is
  visible after confirmation and after reload, and a long line wraps).

Evidence: `harness/log/feat-pr8b-web-assistant-lines.md`.
