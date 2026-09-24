# Feature log: PR-12, stateless intake (Stage 3)

Spec: `harness/context/pr12-stateless-intake-preflight.md`, written first on this
branch. Inputs: build plan row PR-12 and DoD item 2;
`audit-remediation-status.md` §5 item 3; target architecture proposal §3, §4
"Intake" row, §9, §12 Q5. Branch `feat/pr12-stateless-intake` from `origin/main`
@ `04a8ed5` (#96). The spec found no trade-off that needed a stop: no contract
change, no persistence, no model call.

## What changed

- `runtime/services/api/src/proxyloop_api/intake.py` (new): the pure,
  deterministic, model-free parser `propose_intake(text)` (`intake-parser-v1`)
  and the API-local models `IntakeProposalRequest` (`text`, 1–2000 characters,
  strict, no extra keys) and `IntakeProposal` (the four `CreateCaseRequest` keys,
  Money or `null`, `true` or `null`, plus at most one closed-code clarification per
  key). Standard library only, apart from pydantic and `Money`.
- `runtime/services/api/src/proxyloop_api/app.py`: `POST /intake/proposals`, a
  sync `def` handler (threadpool, B2-8) that returns the proposal. No Case,
  Runtime, repository, Temporal, or model call, no lock, and no logging.
  Validation failures reuse the content-free 422 handler.
- `apps/web/lib/runtime-client.ts`: `proposeIntake(text)` posts `{text}` with no
  `Idempotency-Key` and parses the response strictly: exact keys, the known
  parser name, USD safe-integer Money, `true | null`, closed field and reason
  codes, no repeated field.
- `apps/web/app/components/conversation-workspace.tsx`: the first message goes to
  `proposeIntake`. The Draft Task Brief card opens filled from the proposal, and
  each row shows its value or clarification. Only facts the proposal could not
  read are asked for. Composer answers and Edit use the unchanged strict local
  parsing and $72 rules, and a supplied field drops its clarification. Only
  "Create fictional Case" sends the typed facts. The scope reply stays for
  off-topic text with no fact read, and a request over 2000 characters is refused
  locally.
- Docs: `docs/architecture.md` (Experience Layer and Control Plane);
  `CONTEXT.md` gains the term **Intake Proposal**; `audit-remediation-status.md`
  §0 row and §5 item 3.

No canonical contract, `CreateCaseRequest`, browser projection, `runtime.py`, or
committed-artifact change. No DB-gated test was added, so the gated-skip pin is
unchanged at 63. Non-test source diff: 536 added and 23 removed lines.

## Red → green

- Python, `tests/integration/test_stateless_intake.py` (119 items: parser table,
  value rules, keep phrases, an 81-pair parity grid against `CreateCaseRequest`,
  determinism, route in direct and Temporal mode, content-free 422, and privacy
  of the text in the response, logs at DEBUG, and the operation record). Red on
  `main`: collection error `ModuleNotFoundError: No module named
  'proxyloop_api.intake'`. Green: 119 passed. One test case of mine was wrong
  (current $70 with target $72 also breaks the target rule), so it was rewritten
  with a missing target. The parser was not changed for it.
- Web, `lib/runtime-client.test.ts`: 11 new cases failed on `main` (no
  `proposeIntake`). Green: 43 passed.
- Web, `app/components/conversation-workspace.test.tsx`: the branch test file run
  against `main`'s component had 76 of 134 failing. These are the new PR-12
  cases, the rewritten unsupported-intent cases, and every case that goes through
  the card helper. The component was then restored. Green: 134 passed.

## Checks

- `make lint` exit 0.
- `make typecheck` exit 0 (mypy: no issues).
- `make test` exit 0: runtime pytest 1589 passed, 63 skipped; ML pytest 397
  passed, 1 skipped; every committed `*-check` current.
- `make web-check` exit 0: lint, typecheck, vitest 208 passed, `next build`.
- `make preflight` exit 0 on the second run, with gated skips 63 matching the
  per-file pin. The first run failed only
  `ml/tests/test_teacher_pipeline.py::test_concurrent_sampling_matches_the_sequential_run`
  on its wall-clock bound (`0.605 < 0.6`). That test is in `ml/`, untouched here,
  and the machine was loaded (the ML suite took 214 s against 81 s in `make
  test`). It passed in `make test` and on the rerun.

Not run:

- The DB gates (`postgres-check`, `phase05a-check`, `phase06b1-check`) are not
  run. `app.py` changed, so the lane is needed. The new route touches no
  repository or Temporal path.
- The Browser check against the real Runtime is not run. It is needed for the
  full journey of free text → card → confirm → Case → approval → receipt.
- There is no independent review yet.

## Limits

- The $72 rule now has four copies: `CreateCaseRequest`, `runtime.py`, the Web,
  and the parser. Only the parser copy is pinned, by the parity test.
- The Web scope gate `isSupportedMobileBillIntent` still reads free text in the
  browser. It decides only whether an empty proposal is off-topic.
- The parser is lexical and English only. After the review it fails toward
  clarification: a correct but unusual phrasing ("I'd like $80 rather than $92",
  "Hotspot: yes") often yields `ambiguous`, and the consumer then answers one
  prompt. The earlier "went up to $92 reads as a target" limit is closed.
- A model-backed intake is not built (decision 17).
- M-4 (review, recorded only): the 422 log names the key of an unknown field
  (never its value), which is the known #82 limit. A body that is not valid
  UTF-8 gets FastAPI's pre-existing 400 shape, not the 422 body.

## Merge with `main` @ `a8fdf5b` (#97) and the DB lane

- Merging `origin/main` produced `0c58635` with no conflict; the status file
  merged cleanly with both sides kept.
- On `0c58635`:
  - `make test` exit 0: runtime 1713 passed / 63 skipped; ML 397 / 1 skipped.
  - `make preflight` exit 0: vitest 208; gated-skip pin 63.
- The DB gates ran serially from this worktree against the Compose
  `postgres-test` (`127.0.0.1:55432/proxyloop_test`) and `temporal`
  (`127.0.0.1:7233`), with the variables on the make command line only:
  - `postgres-check`: 38 passed.
  - `phase05a-check`: 53 passed.
  - `phase06b1-check`: 56 passed.

## Review follow-up (Request Changes; `harness/code_review/feat-pr12-stateless-intake.md`)

The root decided that any uncertainty becomes a clarification, never a guessed
value. The spec gains dated `intake-parser-v1` rule amendments:

- I-1: contractions, hedges, questions, and later doubt make a feature
  `ambiguous`. The Web labels read values "Read from your message".
- I-2: change, range, history, question, and cue-less amounts have no role, and
  any amount without a role makes both amounts `ambiguous`.
- I-3: the Web keeps the other amount's rule code until its rule passes. It also
  prompts any amount that the local rules still reject.
- M-1: the card opens only on a read value or the scope gate.
- M-2: the failure reply is not repeated.
- M-3: digits are ASCII only. The $999,999.99 cap is enforced in the parser, in
  `CreateCaseRequest` (current bill), and in the Web.
- M-6: the missing tests were added.

Red against the pre-review code:

- 32 of 219 pytest items fail against the `63d1d00` parser. The old module was
  given a `MAX_AMOUNT_MINOR` alias so that it imports.
- 10 of 144 workspace vitest cases fail against the pre-review component.
- The stale-after-Restart case and the `target_not_below_current` release case
  pass on both versions; they are regression tests.

Green, on the amended tree:

- `make lint` exit 0.
- `make typecheck` exit 0.
- `make test` exit 0: runtime 1813 passed / 63 skipped; ML 397 / 1 skipped.
- `make web-check` exit 0: vitest 218 passed, and `next build` succeeded.
- `make preflight` exit 0: gated-skip pin 63.

The DB gates were rerun because `CreateCaseRequest` gained the cap:

- `postgres-check`: 38 passed.
- `phase05a-check`: 53 passed.
- `phase06b1-check`: 56 passed.

## Browser evidence (amended card)

The check used headless Chromium via Python Playwright 1.54 at a 1440x1000
viewport, against the real durable Runtime. Readiness was
`{"ready":true,"adapter_mode":"scripted","storage_mode":"postgres","orchestration_mode":"temporal"}`.
The Web was the production build of the amended tree (`next start`).

Setup (the same method as PR-8b and PR-10):

- Port 8000 is held by an unrelated process, which was not touched.
- A throwaway Compose project, `proxyloop-pr12-browser`, ran postgres on 55472
  and temporal on 7272 on a fresh volume.
- A scratch launcher ran the supervisor's worker, Runtime, and Web commands with
  no model credentials: Runtime on 8012, Web on 3012.
- Playwright forwarded `/api/runtime/**` to 8012.
- Afterwards only those three processes were stopped, and only that project was
  removed with `down -v`. The existing `proxyloop-*` containers,
  `proxyloop_postgres-data`, and `proxyloop-portfolio-demo_postgres-data` are
  unchanged.

The journey:

1. One message: "My mobile bill is $92 and I want to get it under $75. Keep my
   hotspot. (zebra-7731)".
2. The card showed:
   - "$92.00 · Read from your message"
   - "$75.00 · Read from your message"
   - "Required · Read from your message"
   - financing "Missing"

   Create was disabled, and only the financing prompt was asked.
3. The consumer answered "no change". The financing row read "Confirmed ·
   unchanged", and Create was enabled.
4. Create, then "Keep both unchanged and continue", then the pending approval,
   then "Approve exact terms", then the verified receipt.
5. After a reload, the durable restore showed the receipt again. The Status Bar
   read "Done: the Runtime verified completion…", as of Case revision 6.

Runtime calls, in order: `POST /intake/proposals`, `POST /cases`, `GET`,
`POST …/events`, `GET`, `POST …/approvals/{id}`, `GET`, then after the reload
`GET /health/ready` and `GET`. The console had no errors or warnings.

The marker `zebra-7731` was absent from:

- the proposal response;
- `localStorage`, both before Create and after completion;
- the Runtime, worker, and Web logs (0 matches each).

Screenshots are scratch and not committed. They are in
`.../scratchpad/impl-pr12/browser/`, with `result.json`:

- `01-parsed-card.png`
- `02-missing-fact-filled.png`
- `03-case-created.png`
- `04-pending-approval.png`
- `05-verified-receipt.png`
- `06-after-reload.png`
