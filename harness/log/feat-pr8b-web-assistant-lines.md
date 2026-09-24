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
  `conversation-workspace.test.tsx` (+4 cases, 6 runs).

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

## Pending

- Browser verification (§6.6 8b) on `make portfolio-demo`: the assistant line
  visible after confirmation and after reload. It needs 8a's runtime to emit
  `assistant_message`; until then the real backend has no line to show.
- Independent `reviewer`, PR, CI. Merge after 8a and before PR-10/PR-12 touch
  `conversation-workspace.tsx`.

## Limits

- Lines render in cursor order as one group after the Task Brief; the
  Web-authored local messages are not interleaved with them by cursor (they
  have no cursor). With one consumer turn before approval (spec R4) that is the
  whole dialogue.
- React keys are the event cursor; the runtime keeps cursors unique per
  snapshot, and duplicates are not de-duplicated here.
