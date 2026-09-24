# Feature log: PR-8b, the Web shows runtime-authored assistant lines

Spec: `pr8-fast-dialogue-design.md` (frozen 2026-09-24): root decisions 4 and 8,
§1.3, §4.1, §4.3, §6.2 I10, §6.3 AC 7, §6.4 "Web (8b, vitest)", §6.5 8b,
§6.6 8b. Branch `feat/pr8b-web-assistant-lines` from `main` @ `5266b6d`.
8a (runtime, gate, report) is not built yet, so this branch uses fixtures of the
frozen event shape and merges only after 8a.

## What changed

- `apps/web/lib/runtime-client.ts`: new `AssistantLine` type and pure
  `assistantLines(payload)`. It reads only `snapshot.visible_events` and keeps
  entries with `actor === "system"`, `event_type === "assistant_message"`, a
  non-negative integer `event_cursor`, and non-empty string `content`, sorted
  by cursor. Malformed entries are skipped; `parsePayload` still does not
  validate `visible_events`, so dialogue never blocks a Case. `fast` is not read.
- `apps/web/app/components/conversation-workspace.tsx`: `DialogueArtifact`
  renders each line as an `AssistantMessage` bubble with plain React text
  (no HTML) and the decision-8 label, verbatim: "ProxyLoop AI · automated
  message — it cannot accept, sign, or change anything without your
  approval." It sits directly after the Task Brief, under the same phase
  condition, and reads the accepted authoritative payload, so a GET, poll, or
  restore re-renders it. No new fetch, no `fast` parsing, no free-text
  consumer input; the label reuses the existing `artifact-note` class (no CSS
  change).
- Tests: `runtime-client.test.ts` (+3 cases, 6 runs) and
  `conversation-workspace.test.tsx` (+4 cases, 6 runs); review follow-up
  below adds 1 + 3 more.

## Event shape used by the fixtures

The browser projection of a visible event is exactly
`{event_cursor, actor, event_type, content, occurred_at}`
(`VISIBLE_EVENT_KEYS` in `tests/integration/test_browser_projection_allowlist.py`;
`_browser_snapshot` in `app.py`). The canonical `event_id` of §4.1 is not
projected, and §4.2/D6 keep the key set unchanged, so the fixtures carry the
five projected keys: actor `system`, event type `assistant_message`, cursor =
trigger cursor + 1. The Web type is `visible_events?: unknown`; no conflict
with the existing projection types.

## Red, then green

Red on `main`'s source with the new tests: 9 failed, 143 passed (152). The
failures were the 6 `assistantLines` runs (not exported) and the 3 render cases
(after `confirmConstraint`, on restore, `<script>` literal). The three
"nothing renders" runs passed on `main` too, as they should.

Green: 152 passed (152).

Scratch mutation check (not committed): rendering through
`dangerouslySetInnerHTML` fails the literal-text test; dropping the sort fails
the filter test and the restore test; dropping the actor check fails the filter
test and the "only malformed entries" render test.

## Tests added (spec §6.4 Web)

- Filtering: provider and consumer events, a wrong actor with the
  `assistant_message` type, a system event of another type, non-string, empty,
  or whitespace content, negative, fractional, string, or null cursors, and
  non-object entries are ignored; order is by cursor (cursor 0 kept).
  `visible_events` missing, null, an object, or a string gives `[]`.
- A Case read with malformed dialogue entries still parses and keeps a valid
  Task Brief.
- Render after `confirmConstraint` from the GET payload: the POST response
  carries no line, only the GET does; a `fast.response_text` in both is never
  rendered.
- Render on restore (durable profile, stored locator, authoritative GET): two
  lines in cursor order, each labelled.
- `<script>`, `<img onerror>`, and `<b>` content renders as literal text; no
  such element is created and the script does not run.
- Nothing renders with no `visible_events`, with only consumer/Provider events,
  or with only malformed assistant entries.

## Checks

- `make web-check`: exit 0 (eslint clean, `tsc --noEmit` clean, vitest 2
  files / 152 passed, `next build` compiled). The build prints Next's
  "multiple lockfiles" workspace-root warning because the worktree sits inside
  the main checkout; this change does not cause it.
- `make preflight`: exit 0. Ruff format (120 + 90 files) and lint clean, mypy
  66 + 59 files clean, runtime tests 1260 passed / 53 skipped (DB and Temporal
  gated), ML tests 397 passed / 1 skipped, contracts drift check matches, every
  artifact `--check` green, web-check green, lock checks, `compileall`,
  `docker compose config`.
- Not run: DB/Temporal gates (no runtime, API, or Python change; no DB used).

## Merge with 8a and Browser evidence

Merged `origin/main` @ `29c8671` (PR-8a, #94). The status-file conflict was
resolved by keeping both sides' changes (main's In-flight rows plus this
branch's PR-8b row). On the merge: `make web-check` exit 0 (vitest 156
passed); `make preflight` exit 0 (runtime tests 1467 passed / 63 skipped,
gated-skip pin matches 63; ML tests 397 passed / 1 skipped; artifact checks
green).

Browser check (spec §6.6 8b, AC 7), headless Chromium via Python Playwright
1.54 against the real durable Runtime (`scripted` / `postgres` / `temporal`,
readiness `{"ready":true,"adapter_mode":"scripted","storage_mode":"postgres","orchestration_mode":"temporal"}`):

- Deviation from `make portfolio-demo`, same components: port 8000 was held by
  an unrelated local process that was not stopped, and the supervisor and the
  Web's `/api/runtime` rewrite both hardcode 8000. A scratch launcher reused
  the supervisor's own `_start_compose_dependencies` and
  `build_demo_environment` and started the same worker, Runtime, and
  production Web (`next start`, the build from the merged tree) commands, with
  the Runtime on 8001. Playwright forwarded the browser's `/api/runtime/**`
  requests to 8001. No repository file changed.
- The scripted API has one fixed Case id, and the existing
  `proxyloop-portfolio-demo_postgres-data` volume already held that Case
  (`CaseConflictError: case already exists`). Instead of resetting that
  volume, the Compose services ran under a throwaway project
  (`proxyloop-pr8b-browser`, fresh volume), removed with `down -v` afterwards.
  `make portfolio-demo-stop` ran; the demo volume is preserved.
- Flow: intake $92 / $75 / yes / yes, Create fictional Case, then
  "Keep both unchanged and continue". Runtime calls observed: `POST /cases`,
  `GET /cases/{id}`, `POST /cases/{id}/events`, `GET /cases/{id}`, then on
  reload `GET /health/ready`, `GET /cases/{id}`.
- Before confirmation: 0 automated-message labels.
- After confirmation (approval shown): one line, "Thanks. I'm reviewing the
  fictional offer against your constraints now.", with the exact label once.
- After a page reload (durable restore): the same line and label.
- Long line (M2): the scripted lines are short, so a 600-character no-space
  line was injected into the rendered bubble in the live page. With the
  shipped CSS (`overflow-wrap: anywhere`), the line fits its box at 1280x900
  (scrollWidth 707 = clientWidth 707) and 375x812 (307 = 307), with no page
  overflow. Negative control on the same bubble (`overflow-wrap: normal`):
  scrollWidth 4548 against 707 / 307.
- Console warnings/errors: none.
- Screenshots (scratch, not committed): `01-case-created-before-confirm.png`,
  `02-after-confirm.png`, `03-after-reload.png`, `04-long-line-1280.png`,
  `04-long-line-375.png`.

## Pending

- PR, CI, root final review, merge. Merge before PR-10/PR-12 touch
  `conversation-workspace.tsx`.

## Independent review follow-up

Reviewer verdict: Approve with Minors
(`harness/code_review/feat-pr8b-web-assistant-lines.md`). The root accepted
M1–M3 (applied here) and M4 (a log note only, no code change).

- M1: `assistantLines` keeps the first well-formed entry for a repeated cursor
  (a malformed entry at that cursor does not displace a valid one). New tests:
  client "keeps the first well-formed entry for a repeated cursor"; workspace
  "8b M1" (one bubble renders, no React "same key" `console.error`).
- M2: `apps/web/app/globals.css` `.message-bubble` gains
  `overflow-wrap: anywhere`, so a 600-character line with no spaces wraps
  instead of widening the three-column grid. Not covered by a vitest case
  (jsdom does no layout); Browser check pending with 8a.
- M3: workspace "8b M3a" (Case A's line renders; New task removes it; Case B,
  created next with no lines, shows none of A's) and "8b M3b" (after the line
  renders in finalizing, a poll read with a lower revision, then one with the
  same revision and a lower cursor, both without the line, leave it shown).
- M4: see Limits.

Scratch mutation check (not committed): without the dedupe, the client M1
test and the workspace M1 test fail (the bubble count fails first); with
`acceptPayload`'s stale guards removed, M3b fails.

Checks after the follow-up:

- `make web-check`: exit 0 (eslint, `tsc`, vitest 2 files / 156 passed,
  `next build` compiled).
- `make preflight`: exit 0 (ruff format 120 + 90 files, lint clean, mypy 66 +
  59 files clean, runtime tests 1260 passed / 53 skipped DB/Temporal gated, ML
  tests 397 passed / 1 skipped, contracts match, artifact checks green,
  web-check green, lock checks, `compileall`, `docker compose config`).

## Limits

- Lines render in cursor order as one group after the Task Brief; the
  Web-authored local messages are not interleaved with them by cursor (they
  have no cursor). With one consumer turn before approval (spec R4) that is the
  whole dialogue. **M4: once PR-13 brings multi-turn Web dialogue, ordering
  must interleave consumer turns and assistant lines by cursor**; this grouped
  rendering is not sufficient then.
- React keys are the event cursor; M1's dedupe keeps them unique.
