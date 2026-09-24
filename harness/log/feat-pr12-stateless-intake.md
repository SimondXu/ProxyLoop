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
- The parser is lexical and English only. "went up to $92" proposes a $92 target,
  which the consumer corrects on the card.
- A model-backed intake is not built (decision 17).
