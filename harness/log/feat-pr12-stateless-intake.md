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

## Re-review follow-up (I-A + accepted UX rules)

The spec gained a second dated amendment (`intake-parser-v1`, amended before
merge with no version bump). The review artifact gained a re-review section
plus the corrections to M-3, M-4 and M-5.

**I-A / M-5 timing.** Implementer-measured, best of 3, 2000-character input:

| Input | Before (`b31a787`) | After |
|---|---|---|
| `from 1` + 1300 spaces + many `$5` | 1735.0 ms | 0.31 ms |
| `1` + 1000 spaces + many `$5` | 1015.1 ms | 0.35 ms |
| `1` + 1000 tabs + many `$5` | 936.2 ms | 0.34 ms |
| `1 usd` + spaces + many `$5` | 89.3 ms | 0.2 ms |
| repeated "＄⑳" | 385.0 ms | 0.64 ms |
| repeated `$1-` | 173.6 ms | 0.49 ms |

The inputs above now hit the 8-amount cap. The following cases stay under the
cap and exercise the tail bound instead. They took 0.28–1.74 ms after the
change; before the change they were not measured separately.

- `from 1` + 1970 spaces or tabs + 8 × `$5`
- (`from 1` + 240 spaces + `$5`) × 8
- `1 usd` + spaces + 8 × `$5`

The regression test asserts < 250 ms per case.

**Red → green (pytest).** 14 of 245 items fail against the `b31a787` parser:
the timing cases plus the new phrasings. 245 pass after the change.

**Checks on the final tree:**

| Check | Result |
|---|---|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 |
| `make test` | exit 0: runtime 1839 passed / 63 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 219, build |
| `make preflight` | exit 0: gated-skip pin 63 |

**Not run.** The DB gates were not rerun: this round changed only the parser
and the Web, and `CreateCaseRequest` is unchanged since the green gate run. No
new Browser pass was run; the card changes this round are the opening rule and
some copy.

**Remaining.** None of the accepted items is unfinished. The root still owns
the re-review and the PR.

## Third amendment (root decision: when the card opens)

The spec gained a third dated amendment. The Web opens the Draft card when (a) a
proposal field has a value, (b) the scope gate passes, or (c) there is an amount
clarification other than `missing` and the text has a cue from a closed list
(`bill`, `pay`, `paying`, `paid`, `monthly`, `per month`, `a month`, `/mo`,
`carrier`, `phone`, `mobile`, `cell`, `wireless`, `data`, `hotspot`,
`financing`). Otherwise the consumer gets the scope reply.

The first proposed cue list also had bare `plan`, which would open the card for
"Help me plan a vacation for $2,000", contradicting the expected outcome. The
implementer stopped and reported this. The root chose option A and dropped
bare `plan`. Documented limit: "My plan went up to $92", with no other cue, now
gets the scope reply.

Changed: `proposalOpensCard(result, text)` in `conversation-workspace.tsx`; the
fixture `intake-offtopic-proposals.json` gained three real parser outputs ("My
bill is $92 and I'd like $75", "My bill went up to $92 and I want $80", "My plan
went up to $92"). The pytest pin now checks the eight texts in order. The parser
and `intake-parser-v1` are unchanged.

**Red → green.**

- Vitest, `conversation-workspace.test.tsx`: 11 of 169 failed before the change.
  - The three off-topic money texts expected the scope reply.
  - The three new fixture rows had no fixture entry yet.
  - Five negative cue cases: `plan`, `billfold`, `payment`, `months`, `database`.
  All 169 pass after the change. The 16 positive cue cases passed on both
  versions; they are regression tests for the cue list.
- Pytest, `test_off_topic_inputs_read_no_value_and_match_the_web_fixture`:
  failed before the fixture update; 245 of 245 intake items pass after it.

**Merge.** `origin/main` @ `e10443d` (#98, #97) merged cleanly as `f7c49ff`.
Git auto-merged `docs/architecture.md` and
`harness/context/audit-remediation-status.md`. `app.py` did not conflict, and
`config.py` is main's version. The gated-skip pin is main's 66; PR-12 adds no
gated test.

**Checks** (no `PROXYLOOP_TEST_*` variable set):

| Check | Result |
|---|---|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 (mypy: 59 files, no issues) |
| `make test` | exit 0: runtime 1860 passed / 66 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 243 passed (3 files), `next build` |
| `make preflight` | exit 0: runtime 1860 / 66 skipped, ML 397 / 1, vitest 243, gated-skip pin 66 |

**Not run.** The DB gates and a Browser pass were not run: this round changed
only the Web opening rule, a Web fixture, and tests. On this branch, `app.py`,
`CreateCaseRequest` and the parser are unchanged since the last green DB gate
run. The merge brought main's `config.py` and worker changes (#98) unchanged;
this run does not re-verify them against the real dependencies.

## Fourth amendment (focused re-review: I-1, M-1..M-5)

The spec gained a fourth dated amendment (`intake-parser-v1`, still unmerged).
Changed: `intake.py` (I-1 `get`, M-1 cap, per-sentence doubt and bounded
scans, M-2, M-3); `conversation-workspace.tsx` (M-4 rule (c), M-5 copy); the
fixture gained "Which phone should I take on a euro trip?" (real parser
output); the pytest pin and tests.

**Red → green.**

- Pytest: the final test file against the pre-change parser (constant
  `NORMALIZED_TEXT_MAX_LENGTH` added only so that it imports) fails 19 of 267.
  - I-1: 6.
  - M-2: 7, including the four former-value phrasings.
  - M-3: 4.
  - M-1 cap: 2.

  All 267 pass after the change. "Could you get my mobile bill down to $75?"
  passes on both versions and guards against over-restricting `get`.
- Vitest, `conversation-workspace.test.tsx`: 9 of 176 failed before the change.
  - M-5: 422, 404, 409, 500, 503, network, 200 non-JSON, 200 invalid proposal.
    These run through the real client with a stubbed `fetch`.
  - M-4: the euro-trip row. It still failed once its fixture entry was added.

  All 176 pass after the change.

**Timing** (best of 3 to 5, implementer-measured with the reviewer's
`timing.py` / `timing2.py` plus the pytest table; ms):

| Input | NFKC length | Before | After |
|---|---|---|---|
| U+FDFA x 2000 | 36000 | 4.55 | 1.22 (refused) |
| keep hotspot + U+FDFA pad + `$` | 34220 | 14.51 | 1.16 (refused) |
| U+FDFA pad + 8 x `$5` | 35574 | 32.71 | 1.19–1.33 (refused) |
| keep hotspot, 350 x `№, ` + U+FDFA | 18262 | 67.80 | 0.58–0.63 (refused) |
| keep hotspot, 450 x `№, ` + U+FDFA | 13262 | 63.58 | 0.41 (refused) |
| keep hotspot, `no, ` + U+FDFA pad | 15362 | 49.65 | 0.46 (refused) |
| keep hotspot, 500 x `no, ` | 2000 | 12.02 | 0.83–0.85 |
| keep hotspot and `no` x 300 | 2000 | 7.05 | 0.55 |
| near the cap: U+FDFA x 100, keep hotspot, 470 x `no, ` (read) | 3694 | not measured | 1.17–1.22 |

Every other reviewer input stays under 0.6 ms. The pytest timing table (13
cases) asserts < 250 ms per case; its largest measured value is 1.33 ms.

**Checks:**

| Check | Result |
|---|---|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 (59 files, no issues) |
| `make test` | exit 0: runtime 1882 passed / 66 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 250 passed, `next build` |
| `make preflight` | exit 0 on the second run: runtime 1882 / 66, ML 397 / 1, vitest 250, gated-skip pin 66. The first run failed `format-check` only: one new test assertion was not ruff-formatted. It was rewritten; no behavior changed. |

**Not run.** The DB gates and a Browser pass were not run. This round changed
the parser, the Web opening rule and failure copy, and tests. It did not
change `app.py`, `CreateCaseRequest`, or any repository or Temporal path.

### M-2 replaced by the root's tiered rule

The root did not accept the implementer's "nearer current cue" reading. It
made too many common target phrasings ambiguous. The root's tiered rule
replaces it; the full rule is in the spec. In short: a target cue beats a weak
current cue, and a target cue that meets a strong current cue leaves the
amount without a role.

Under this rule the two target tiers act the same, so the parser has one
target list and a separate strong-current list. Four implementation choices
are recorded in the spec:
- `plan` is not a cue before an amount; the vacation case stays off-topic.
- "I am paying" is strong, the same as "I'm paying".
- The `to` in "comes to" is not a target cue.
- `happy at` is also a strong current cue, so "I'd be happy at $75" is
  ambiguous too.

"would like to pay $80.25" is back in the comma-grouping test. "My budget is
$75", "I only want to pay $75" and "My target is $75 and my bill is $92" are
back to reading values.

**Red → green.** The final test file against the `b16c97f` parser fails 9 of
275:
- the four restored value rows;
- four strong-target rows: "My target is $75", "My budget is $75", "I only
  want to pay $75", "I would like to pay $80";
- the new "My bill comes to $92" row.

All 275 pass after the change. The three root ambiguous examples, the I-1 set,
and "Could you get my mobile bill down to $75?" pass on both versions.

On a 25-sentence phrasing corpus, the amounts now match the parser from before
the fourth amendment, except the intended I-1 cases. The corpus is in the
scratch directory, not committed.

**Checks** (tiered rule):

| Check | Result |
|---|---|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 (59 files, no issues) |
| `make test` | exit 0: runtime 1890 passed / 66 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 250 passed, `next build` |
| `make preflight` | exit 0: runtime 1890 / 66, ML 397 / 1, vitest 250, gated-skip pin 66 |

**Not run.** The DB gates and a Browser pass were not run; only the parser's
role cues and tests changed in this step.

## Fifth amendment (final review: I-1, I-2/M-b, M-a, M-c)

Changed: `intake.py` has three changes:
- `_HISTORY` searches the whole clause before the amount again.
- The role-cue scans read the segment since the previous amount, then the
  whole clause before the amount, instead of the tail.
- `_RETRACTION` is extended. None of its patterns has adjacent optional
  whitespace.

The implementer also removed the fourth-amendment `comes to` exclusion
("I hope it comes to $75" had become a guessed current bill of $75). Tests
and the spec amendment are updated. M-c: no change, as it matches the spec.

**Red → green.** 21 new test items fail against `6f34ff0`, and all 296 pass
after the change:
- M-a: 10 new retraction rows plus 1 same-sentence case;
- I-1: 5 history sentences;
- I-2 / M-b: 1 distant target cue and 2 distant strong-current cues;
- "comes to": 2 rows.

The earlier required sets still pass: the I-1 `get` set, the tiered-cue set,
and "My bill is $92 and I'd like $75" → 92 / 75.

**Timing** (best of 5, ms; the reviewer's `timing_c.py` against `6f34ff0` →
this change):

| Input | NFKC length | Before | After |
|---|---|---|---|
| `№ ` x ~cap, one clause, 8 × `$` | 2988 | 0.60 | 3.66 |
| 8 amounts separated by `№` runs | 2991 | 0.61 | 1.97 |
| ﬃ words ~cap + 8 amounts | 3924 | 0.70 | 1.33 |
| 8 amounts separated by ㎓ runs | 3912 | 0.50 | 1.10 |
| keep hotspot, `№, ` ~cap | 2662 | 1.09 | 1.10 |
| above cap max (U+FDFA × 2000) | 36000 | 1.18 | 1.16 |

The other `timing_c.py` inputs take 0.3–0.8 ms. The earlier `timing.py` and
`timing2.py` inputs take ≤ 1.21 ms.

The pytest timing table gained the slowest new input, "one clause, 988 × No-sign,
8 × $5", at 3.60 ms. There are now 14 cases, each asserted < 250 ms; the
largest measured is 3.60 ms.

**Every changed reading between `0b589f4` and this head** on the reviewer's
corpora: `corpus.txt` 11 of 394, `tier.txt` 2 of 137, `tail2.txt` 1 of 8,
`tail.txt` 31 of 94.

Columns are current / target / hotspot / financing. "–" means no value: the
field has a clarification. No changed reading gains or changes a value (checked
by script): every change turns a value into a clarification.

`corpus.txt` (11 changed):

| Text | 0b589f4 | head |
|---|---|---|
| Can I get it lower than $92? | – / $92 / – / – | – / – / – / – |
| Hoping you can explain why my bill is $92 | – / $92 / – / – | – / – / – / – |
| I'd like to lower my phone bill that is currently $92 | – / $92 / – / – | – / – / – / – |
| I'm happy at $92, I'd rather keep it | – / $92 / – / – | – / – / – / – |
| Is $80 realistic to get? | $80 / – / – / – | – / – / – / – |
| Is it lower than $92? | – / $92 / – / – | – / – / – / – |
| My bill comes to $92 | – / $92 / – / – | – / – / – / – |
| My goal is what I'm paying right now: $92 | – / $92 / – / – | – / – / – / – |
| Should I get the $92 plan? | $92 / – / – / – | – / – / – / – |
| Should I get the $92 plan? I want to pay under $80. | $92 / $80 / – / – | – / – / – / – |
| Why did my bill get to $92? | – / $92 / – / – | – / – / – / – |

`tier.txt` (2 changed):

| Text | 0b589f4 | head |
|---|---|---|
| Under my plan it costs $92 | – / $92 / – / – | – / – / – / – |
| Under my plan it is $92 | – / $92 / – / – | – / – / – / – |

`tail2.txt` (1 changed):

| Text | 0b589f4 | head |
|---|---|---|
| I pay for the phone that I really want to keep on my account each month $92 | – / $92 / – / – | – / – / – / – |

`tail.txt` (31 changed):

| Text | 0b589f4 | head |
|---|---|---|
| My goal for this whole negotiation with the carrier over my phone bill is $75 | – / $75 / – / – | – / – / – / – |
| My target for the total amount that appears on my monthly phone bill is $75 | – / $75 / – / – | – / – / – / – |
| My target for the total amount that appears on my monthly phone bill is $75. I pay $92. | $92 / $75 / – / – | – / – / – / – |
| I pay $92. My target for the total amount that appears on my monthly phone bill is $75. | $92 / $75 / – / – | – / – / – / – |
| I pay $92. My budget for the total amount that shows up each month on the bill is $80. | $92 / $80 / – / – | – / – / – / – |
| I want to be paying something like a lot less than what I pay now $92 | – / $92 / – / – | – / – / – / – |
| I hope it comes to $75 | – / $75 / – / – | – / – / – / – |
| I hope it comes to $75, keep hotspot | – / $75 / keep / – | – / – / keep / – |
| Ideally it comes to $75 and I pay $92 now | $92 / $75 / – / – | – / – / – / – |
| Hopefully it comes to $75. I'm on the $92 plan. | $92 / $75 / – / – | – / – / – / – |
| Could you get my bill lower than $92? | – / $92 / – / – | – / – / – / – |
| Why is it lower than $92? | – / $92 / – / – | – / – / – / – |
| Is it possible to get it cheaper than $92? | – / $92 / – / – | – / – / – / – |
| Keep hotspot, keep financing unchanged. Wait, no, I pay $92, target $80. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Wait no. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. No. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. No! | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Nah. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Never mind. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Nevermind. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Scratch that. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Scratch that, keep only the hotspot. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Forget that. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Ignore that. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Disregard that. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Cancel that. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. On second thought, no. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. Just kidding. | $92 / $80 / keep / keep | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. No, sorry. | $92 / $80 / keep / – | $92 / $80 / – / – |
| I pay $92, target $80, keep hotspot, keep financing unchanged. No wait. | $92 / $80 / keep / – | $92 / $80 / – / – |
| Keep hotspot and financing unchanged. Never mind the rush. I pay $92, target $80. | $92 / $80 / keep / – | $92 / $80 / – / – |

**Checks** (fifth amendment):

| Check | Result |
|---|---|
| `make lint` | exit 0 on the second run. The first run failed on one comment line over 88 characters (E501); the comment was rewrapped. |
| `make typecheck` | exit 0 (59 files, no issues) |
| `make test` | exit 0: runtime 1911 passed / 66 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 250 passed, `next build` |
| `make preflight` | exit 0, after the rewrap: runtime 1911 / 66, ML 397 / 1, vitest 250, gated-skip pin 66 |

**Not run.** The DB gates and a Browser pass were not run: only the parser,
its tests, and the harness docs changed.

## Final verification: `like it (to be|at)` removed

The verification confirmed the fifth-amendment fixes. It found one remaining
source of a guessed value: the target cue `like it (to be|at)`, added in the
`0b589f4..6f34ff0` range. With it, "I don't like it at $92" read as target $92.
Root decision: the branch is deleted, and the spec's fifth amendment records
it.

- **Red → green.** Three new items fail with the branch and pass without it.
  - "I like it at $92" → current $92, target `missing`. Not ambiguous: `at`
    is a weak current cue.
  - "I don't like it at $92" → current $92, target `missing`.
  - "It's $95 now, I don't like it at $95, keep hotspot, keep financing
    unchanged" → current $95, target `missing`.

  299 intake items pass. The M-2 required outcomes all still pass, and "I'd
  like it at $75", "I want it at $75" and "I want it to be $75" still read
  target $75.
- **Fuzz.** The reviewer's `fuzz.py` (`0b589f4` against head):

  | Parser | Seeds | Inputs per seed | Readings that gain or change a value |
  |---|---|---|---|
  | head | 1, 2, 3 | 100,000 | **0** |
  | head | 1, 2, 3 | 20,000 | 0 |
  | before the deletion (`7d684ed`) | 1, 2, 3 | 20,000 | 76, 78, 72; every one contains `like it at` |

**Checks:**

| Check | Result |
|---|---|
| `make lint` | exit 0 |
| `make typecheck` | exit 0 (59 files, no issues) |
| `make test` | exit 0: runtime 1914 passed / 66 skipped; ML 397 / 1 skipped |
| `make web-check` | exit 0: vitest 250 passed, `next build` |
| `make preflight` | exit 0: runtime 1914 / 66, ML 397 / 1, vitest 250, gated-skip pin 66 |

**Not run.** The DB gates were not rerun: they passed 38 / 53 / 56 after the
first review round, and the later rounds changed only the parser, the Web
opening rule and copy, tests, and docs. No new Browser pass was run; the last
one is the amended-card journey above.

The review artifact now covers every round. Final verdict: Approve, after the
`like it` branch was removed.

Docs-only follow-up, made after the `make preflight` run above: the
`docs/architecture.md` intake paragraphs now describe the amended rules:
- the card-opening rule (c) with its closed cue list and the M-4 exclusion;
- the intake failure copy;
- the tiered role cues;
- the 4000-character NFKC cap;
- retractions.

`make lint` exit 0 afterwards.
