# Phase log: Phase 07, Portfolio Hardening (PR-16)

Contract: `harness/build/phase-07-portfolio-hardening.md`, frozen 2026-09-25
with root decisions D1–D9. Branch `feat/pr16-phase07-contract`, which merged
`origin/main` @ `973258a` (#102, PR-14). `harness/status.toml` is now
`in_progress`, with phase `07`.

## What PR-16 adds

- **D2, ports.** Scene 0 and every scene command can now take other loopback
  ports.
  - `serve --runtime-port/--web-port`, with Make variables `RUNTIME_PORT` and
    `WEB_PORT`. The defaults stay 8000 and 3000.
  - `validate_demo_ports` refuses the following before anything starts:
    - a port out of range;
    - the same port for Runtime and Web;
    - 55433, 7234 or 55434, which the demo's PostgreSQL, Temporal and
      recovery services use.
  - `_check_startup_ports` probes exactly the selected ports. A taken port
    still fails closed, and the launcher never picks another port.
  - `build_demo_environment` always derives `PROXYLOOP_RUNTIME_ORIGIN` from
    the Runtime port, so a value inherited from the shell is overridden. It is
    set for the Web build, the worker, the Runtime and `next start`.
  - `apps/web/next.config.ts` reads that variable through the new
    `apps/web/lib/runtime-origin.ts`. It accepts only
    `http://{127.0.0.1|localhost}:port` (review M1 removed `[::1]`), with no path, query or
    credentials. Anything else throws, so the build fails. The default is
    `http://127.0.0.1:8000`.
  - `portfolio-demo-channel` and `portfolio-demo-journey` pass
    `--runtime-url http://127.0.0.1:$(RUNTIME_PORT)`.
- **D3, Scene J.** `make portfolio-demo-journey` runs the `journey`
  subcommand of `scripts/run_phase_07a_portfolio_demo.py`.
  - It first requires fresh state. It then calls the same routes the Web
    uses, in order:
    1. readiness, which must report `postgres` storage and `temporal`
       orchestration;
    2. `POST /intake/proposals` with the marker message;
    3. `POST /cases`, built from the three facts the intake read plus
       financing set to `true`;
    4. `POST …/events` with the Web's exact `CONFIRMATION_EVENT`;
    5. `POST …/approvals/{id}`;
    6. an exact replay of the approval (same body and `Idempotency-Key`);
    7. a final `GET`.
  - It asserts:
    - the confirmation produced exactly offer, then consumer turn, then
      assistant line;
    - on the scripted backend the assistant line is
      `SCRIPTED_DIALOGUE_LINES[0]`;
    - the approval is pending after the confirmation;
    - `execution_count` is 1 after the approval, the replay and the final
      read;
    - the replay leaves the revision unchanged;
    - the Web receipt predicate holds, restated in Python as
      `completion_has_verified_evidence`;
    - `list_model_traces` returns exactly slow, judge and fast
      `{succeeded: 1}` each, which means no Judge retry;
    - the marker is absent from the proposal response and from `runtime.log`,
      `worker.log` and `web.log`.
  - `WRITE_EVIDENCE=1` writes the content-free
    `data/evaluation/phase-07-demo-journey-scripted.json`. It carries no ids,
    timestamps, latencies or text, and it is written for the scripted backend
    only.
  - It prints a note, and does not fail, when the revisions differ from the
    reference 2/4/6.
- **D5, ops report.** `make ops-report` and `make ops-report-check` run
  `scripts/run_ops_report.py`. The check is part of `make test`.
  `data/evaluation/ops-report.json` holds:
  - the 23 `*-check` targets that `make test` runs;
  - the three real-dependency gates, with their test files and the number of
    test items `pytest --collect-only` collects: `postgres-check` 38,
    `phase05a-check` 73, `phase06b1-check` 56;
  - the gated-skip pin (66, every pinned file inside a gate);
  - the split reports: scripted v2 with the Judge counts, and distilled and
    untuned marked pre-Judge;
  - the M1 and M2 headlines, with labels, claim boundaries and caveats;
  - trace-health invariants;
  - the Scene J evidence, marked `not_recorded` until the lane run;
  - the not-done list.

  Data inputs are pinned by SHA-256. The Makefile and the pin script are
  pinned only through the fields derived from them.
- **Harness and docs.**
  - `harness/status.toml` is `in_progress`.
  - `PLANS.md` shows the Phase 07 row as in progress.
  - The status file §0 has a Phase 07 row.
  - `docs/portfolio-demo.md` describes the real journey order (D9), Scene J,
    ports, `ops-report`, distilled-scene details and the not-done list.
  - `docs/architecture.md` has a Phase 07 paragraph.
  - `docs/development.md` and the demo section of `README.md` are updated.

The only Runtime source change is F1's logging handler in
`proxyloop_api/server.py` (amendment A1). None of the hot files changed, no
committed `*-check` artifact moved, and the gated-skip pin is unchanged at 66.

## Finding F1 and root decision (b), 2026-09-25

The contract's Scene J expects "one JSON operation record per journey
request in the Runtime log". Before F1 that could not be observed:

- `JsonLoggingOperationRecorder` logs at INFO to `proxyloop_api.operations`.
- `proxyloop_api/server.py` ran uvicorn with `log_level="error"` and attached
  no handler to that logger, so INFO records fell through to Python's
  last-resort handler, which prints WARNING and above only.
- A local probe confirmed it. A direct-mode server on port 8123 answered
  `POST /intake/proposals` and `GET /health/ready` and wrote nothing.

The root chose option (b), recorded as contract amendment A1:

- `configure_operation_logging()` in `server.py` attaches one stderr
  `StreamHandler` at INFO. The handler uses the existing JSON message as the
  line, and `main()` calls it before `uvicorn.run`.
- Scene J's check is restored: `health_ready`, `intake_proposal`,
  `create_case`, `append_event` and `get_case` once each, `decide_approval`
  twice, all 2xx with category `none`.
- `ops-report` copies those counts from the journey evidence.
- Red → green:
  - Red: `tests/integration/test_operation_log_emission.py` runs the real
    server command, sends one intake request, and reads stderr. It failed
    with `assert 0 == 1`.
  - Green: it passed after the handler was added.
- Three new unit tests cover the journey check: one record per request, a
  missing record, and an extra or failed record.

The #103 merge closed the PR-9b reload limit, so the distilled scene now
includes a reload.

## Red → green

- **Red.**
  - `tests/integration/test_phase_07a_portfolio_demo.py` with the new D2 and
    Scene J tests: collection error,
    `AttributeError: … no attribute 'RECOVERY_POSTGRES_PORT'`.
  - `apps/web/lib/runtime-origin.test.ts`: the test file failed to load because
    the module did not exist.
  - `tests/integration/test_ops_report.py`: 3 of 10 failed. The failing tests
    were the Makefile wiring, the committed report and `ops-report-check` in
    `make test`. I wrote these tests after the script, so the red covers only
    those parts.
- **Green.** Demo tests 49 passed, including one updated existing test: the
  `serve` lambda now accepts the port kwargs. Ops-report tests: 10 passed.
  runtime-origin vitest: 12 passed.
- **Build checks.**
  - `PROXYLOOP_RUNTIME_ORIGIN=http://127.0.0.1:8011 pnpm --filter
    @proxyloop/web build`: exit 0, and `routes-manifest.json` rewrites to
    `http://127.0.0.1:8011/:path*`.
  - The same build with `http://example.com:8000`: exit 1, with the
    `PROXYLOOP_RUNTIME_ORIGIN must be a loopback …` error.
  - The default build from `make web-check` rewrites to
    `http://127.0.0.1:8000/:path*`.

## Checks at the first PR-16 commit (`d6cf93f`)

- `make lint`: exit 0. The first run failed on 5 E501 errors; `ruff format`
  fixed them.
- `make typecheck`: exit 0.
- `make test`: exit 0. Runtime 2109 passed, 66 skipped.
- `make web-check`: exit 0, vitest 262 passed.
- `make preflight`: exit 0, 66 gated skips.

## Lane run (2026-09-25; DB/Compose lane held exclusively)

Every scene ran from the documented commands, with `RUNTIME_PORT=8011` and
`WEB_PORT=3011`. That exercises D2, and it leaves any process on 8000 alone;
at this run 8000 and 8765 were in fact free. Before each scene the demo ran
`make portfolio-demo-stop` and then `make portfolio-demo-reset`, which prints
its scope and removes only `proxyloop-portfolio-demo_postgres-data`. The
other `proxyloop-*` containers and volumes were not touched. Screenshots and
`result.json` files are in the scratch directories `impl-pr16/scene-a/` and
`impl-pr16/scene-ad/` (not committed).

| Scene | Result |
|---|---|
| 0 startup | **pass** |
| A Web journey (scripted) | **pass**, with one expected-text deviation (amendment A2) |
| J journey driver | **pass**, twice, byte-identical |
| A-D distilled (manual) | **pass** |
| B mailbox | **pass** |
| R recovery | **pass** |

**Scene 0, startup.**
- The banner listed the Web at `http://127.0.0.1:3011`, Runtime readiness at
  `http://127.0.0.1:8011/health/ready`, Temporal at `127.0.0.1:7234`, "Fast
  backend: scripted", the scene order, the logs and the stop command.
- Readiness returned
  `{"ready":true,"adapter_mode":"scripted","storage_mode":"postgres","orchestration_mode":"temporal"}`.
- The Web's own rewrite reached the Runtime:
  `GET http://127.0.0.1:3011/api/runtime/health/live` returned 200.
- Fail-closed checks:
  - `RUNTIME_PORT=55433` was refused with "Runtime port 55433 is reserved for
    the demo PostgreSQL".
  - `RUNTIME_PORT=WEB_PORT=8012` was refused with "Runtime and Web port must
    differ".
  - With a scratch listener holding 8011, the demo refused with "required
    host port 8011 is unavailable" before starting Compose.
- The banner reaches a piped file only at exit, because stdout is buffered.
  `PYTHONUNBUFFERED=1` shows it immediately.

**Scene A, Web journey (scripted).** Headless Chromium through Python
Playwright 1.54, with no route forwarding.
- Intake card:
  - "$92.00 · Read from your message", "$75.00 · Read from your message",
    "Required · Read from your message", and financing "Missing".
  - Create stayed disabled until the answer "no change", after which the row
    read "Confirmed · unchanged".
- After create: the Status Bar read "Waiting for you to confirm the Task
  Brief.", as of Case revision 2, phase Strategy, approval None, execution Not
  started. The contract expected "Planning from your confirmed goal." here;
  see amendment A2.
- After confirm:
  - One assistant line: "Thanks. I'm reviewing the fictional offer against
    your constraints now.", with the label "ProxyLoop AI · automated message
    — it cannot accept, sign, or change anything without your approval.".
  - The Status Bar read "Waiting for your approval of the exact terms.", as
    of revision 4, "Pending · expires 2026-09-25T02:48:31.801782Z", the same
    expiry as the approval card.
- After approve: the Status Bar read "Done: the Runtime verified completion
  against Provider Evidence.", as of revision 6, "Executed 1 time", "Verified
  complete · 1 matching Evidence ID · receipt shown". The receipt was shown.
- After reload: identical rows.
- Mobile, 375x812:
  - The intake card read the same, with no horizontal overflow.
  - The restored receipt showed the same assistant line, with no overflow.
  - The Status Bar was hidden, which is the recorded rail limit below
    1120 px.
- Desktop had no overflow.
- The console had no errors or warnings.
- The marker `zebra-7731` was absent from `localStorage` (before create and
  after completion), from the proposal responses, and from `runtime.log`,
  `worker.log` and `web.log`.
- Runtime calls: `POST /intake/proposals`, `POST /cases`, `GET`,
  `POST …/events`, `GET`, `POST …/approvals/{id}`, `GET`, then after the
  reload `GET /health/ready` and `GET`.
- `runtime.log` held 15 operation records: the supervisor's readiness probe,
  two manual probes, and the 12 Browser requests.

**Scene J, journey driver.**
- Ran `make portfolio-demo-journey RUNTIME_PORT=8011 WRITE_EVIDENCE=1`. It
  passed:
  - intake read three facts and asked one;
  - one model line and a pending approval;
  - one execution, unchanged by the exact replay;
  - the receipt predicate held;
  - traces fast, judge and slow were each `succeeded 1`;
  - 7 operation records, all with category `none`;
  - the marker was absent.
- Revisions were 2, 4 and 6, matching the reference.
- A second run after stop, reset and start produced a byte-identical
  `data/evaluation/phase-07-demo-journey-scripted.json` (`cmp`).
- `make ops-report` then reported "Scene J journey evidence: recorded". Both
  artifacts were committed in `ab59886`.

**Scene A-D, distilled (manual).**
- Base snapshot: the cached `Qwen3-8B-MLX-bf16` revision `6766fd4b`, present.
- Adapter:
  - `make phase03c-mlx-adapter` with `PHASE03C_PEFT_ADAPTER` pointing at the
    main checkout's git-ignored PEFT adapter converted it into this
    worktree's git-ignored `mlx/` directory. The result "matches
    ml/serving/phase-03c-cloud-run-01-mlx-attestation.json".
  - `uv sync --project ml --extra evaluation --offline` installed
    `mlx-lm` 0.31.3 from the uv cache. No download happened.
- Gateway: `make local-fast-gateway BACKEND=distilled LOCAL_FAST_PORT=8775`,
  with `HF_HUB_OFFLINE=1` from the Make target. Its `/v1/identity` reported
  identity fingerprint `c83bdd6b…`, the same as the M2 report, labelled
  "local opt-in candidate".
- Demo: `PROXYLOOP_FAST_GATEWAY_URL=http://127.0.0.1:8775 make portfolio-demo
  FAST_BACKEND=distilled RUNTIME_PORT=8011 WEB_PORT=3011`.
  - The banner read "Fast backend: distilled (local opt-in candidate; the
    gateway is not supervised by this demo)".
  - Readiness reported `adapter_mode` `local_distilled_candidate`.
- Browser run (the same script):
  - After confirm, the assistant line was the fallback "I am checking that
    and will update you.", with the label.
  - The Fast trace was `rejected` by the gate (`fast_gate_completion`,
    `fast_gate_dialogue_act`, `fast_gate_number_not_allowed`). It came from
    model `Qwen/Qwen3-8B-MLX-bf16`, version `distilled:c83bdd6ba873cb8f`,
    provider `local_mlx_gateway`, in 22 683 ms. The gateway logged one
    `POST /v1/fast/decide` with 1876 input and 184 output tokens.
  - The slow and judge traces were `succeeded`.
  - Approval, `execution_count` 1 and the verified receipt matched Scene A.
    The reload restored the receipt, which #103 now allows.
  - The console was clean and the marker was absent.
- This is one local observation, not a latency or quality claim.
- The gateway process was stopped afterwards.

**Scene B, mailbox.** `make portfolio-demo-channel RUNTIME_PORT=8011`
returned "Scene B passed: … one verified inbound, one deduplicated replay,
one accepted synthetic delivery, one delivered callback, and two
authoritative channel Evidence records.", followed by "Browser projection
isolation passed".

**Scene R, recovery.** `make portfolio-demo-recovery` passed 1 test, then
printed "Recovery check passed: the accepted Phase 06B1 lost-response retry
preserved one logical local delivery.". Only the demo project's
`postgres-test` service was started and then stopped.

**Real-dependency gates.** These ran serially, with the demo stopped,
against the shared `postgres-test` (55432, `proxyloop_test`) and `temporal`
(7233). The variables were set on the make command line only.

| Gate | Result |
|---|---|
| `make postgres-check` | 38 passed |
| `make phase05a-check` | 73 passed (116.57 s) |
| `make phase06b1-check` | 56 passed |

## Final checks (after the lane run)

`make lint typecheck test web-check preflight` exited 0:
- lint: all checks passed.
- mypy: 79 and 70 source files.
- Runtime tests: 2113 passed, 66 skipped.
- ML tests: 499 passed. `mlx-lm` is now installed, so the previously skipped
  MLX test ran.
- `ops-report.json is current`.
- vitest: 268 passed, and the Web build passed.
- Gated skips were 66 and matched the per-file pin.

## Root decisions after the lane

- A2 is confirmed (2026-09-25). The Status Bar after create reads "Waiting
  for you to confirm the Task Brief.", which is current product behaviour
  after the PR-10 review fix. Removing the #103 reload limit from the docs is
  also confirmed.

## Independent review (PR-16): Approve, with 8 Minors

The root decided each Minor, and all eight are applied:

1. **`[::1]` removed.** `runtime-origin.ts` now accepts only 127.0.0.1 and
   localhost. `[::1]` passed validation, but Next's `prepareDestination` fails
   on it at request time with "Missing parameter name at 1". A new vitest case
   asserts it is refused: it failed red, then passed.
2. **Comments corrected.** The `runtime-origin.ts` header and
   `docs/architecture.md` now say the destination is fixed at build time and
   that `next start` only re-validates it.
3. **Not-done list completed.** `NOT_MEASURED` in `scripts/run_ops_report.py`
   and the not-done list in `docs/portfolio-demo.md` now cover every DoD-6
   item. The additions are production exactly-once effects, monitoring and
   readiness; hosting; the build-plan "Do not do" list; Web free-text turns,
   Web-exposed channels or the Judge, and UI redesign; and hosted spend.
   `ops-report.json` was regenerated.
4. **Architecture edits ratified.** The root accepted the
   `docs/architecture.md` edits as a description of what is built. PR-17
   continues the A-7f reconciliation.
5. **Contract amendment A3.** A Web restore on a local backend was done by
   #103, so the Non-goals list and Scene A-D are corrected. D7's "no reload"
   is superseded.
6. **M1 boundary referenced, not restated.** Its text predates M2 and calls
   M2 pending, so the report now points to the source file and notes that M2
   is reported below. A new test asserts the committed report contains no
   "M2 is pending" or "(needs PR-" text.
7. **Socket-isolation test.** It now runs `main(["--check"])` with
   in-process socket connect blocked and the collector stubbed with the
   committed counts. `collect_count`'s docstring states that its
   `pytest --collect-only` subprocess only imports and collects test modules,
   so it opens no connection. `build_report` resolves its collector at call
   time so the stub applies.
8. **`configure_operation_logging` unit test.** A repeated call returns the
   same single handler. `propagate` is False, the logger level is INFO, and
   the root logger and an unrelated logger keep their levels. A logged message
   is written to the stream as the bare line.

None of these changes touch runtime or storage behaviour: they are Web
config validation, the ops report, tests and docs. The DB gates run on
`ecfef63` (`postgres-check` 38, `phase05a-check` 73, `phase06b1-check` 56)
therefore stand, and were not rerun.

## Merge of R-6 (#104) and gate rerun (2026-09-25)

The branch merged `origin/main` @ `1309c71` (#104, R-6: an injectable offer
TTL stored as an optional v3 Provider field).

- The status-file conflict was resolved by keeping both rows.
- The gated-skip pin now comes from `main`: 67 in total, with
  `test_phase_04c_persistent_case_store.py` at 30. PR-16 adds no gated test,
  so the per-file sum is `main`'s pin.
- `ops-report.json` was regenerated:
  - `postgres-check` now collects 39 test items;
  - the pin reads 67.

R-6 changed `runtime.py`, `postgres_repository.py` and the Provider
underneath the Phase 07 scenes, so the three DB gates were rerun serially on
the merged head, with the demo stopped:

| Gate | Result |
|---|---|
| `make postgres-check` | 39 passed |
| `make phase05a-check` | 73 passed (116.04 s) |
| `make phase06b1-check` | 56 passed |

`phase05a-check` also printed one `BrokenPipeError` traceback from the
test-only fake gateway's server thread (`local_fast_fake_gateway.py`, `_send`).
This happens when a timeout test's client disconnects before the fake writes
its reply. The traceback came after the passing result, and no test failed.

The demo scenes were not rerun. R-6 keeps the default TTL unchanged (1 h),
so the scenes' behaviour is unchanged, and none of the three gates failed. The
lane-run evidence above therefore stands.

Final checks on the merged head: `make lint typecheck test web-check
preflight` exited 0.
- lint: passed.
- mypy: 79 and 70 source files.
- Runtime tests: 2150 passed, 67 skipped.
- ML tests: 499 passed.
- `ops-report.json is current`.
- vitest: 269 passed, and the Web build passed.
- Gated skips were 67 and matched the per-file pin.

# PR-17: final reports

Branch `docs/pr17-phase07-reports`, cut from `origin/feat/pr16-phase07-contract`
@ `ecfef63` while PR-16 was in review, then brought up to date with
`origin/main` @ `abd1027` (PR-16 squash merged as #105, which includes #104)
by a merge, not a rebase. Docs only: no code, contract, schema,
test or committed `*-check` artifact changes. `harness/status.toml` is
unchanged; it returns to `idle` in the final commit at the gate.

## What PR-17 adds

- **`docs/ml-evidence.md`, final pass.**
  - A one-paragraph summary at the top.
  - A new section, "The product path: a negative result". Its table puts the
    trained path (cloud A1/A3, local M1) next to the product path (M2):
    distilled 0/240 delivered and act agreement 157/240 = 0.654
    [0.592, 0.711]; untuned 8/240 and 97/240. It gives the causes
    (refusal-transfer refused before the model, −40; D4 on
    unsupported-action, −40; about half each) and the latency (64/200 over
    25 s).
  - A "Claim boundaries" section: the four 03C caveats, E1–E5, D3–D6, one
    machine, not p95, not production.
  - The "Six things" list had five items (1, 2, 3, 5, 6); it is renumbered
    "Five things".
  - The Modal figure separates the run (≈ USD 18.09) from the phase total
    (USD 22.25). The teacher figure names USD 121.59 as the v6 run and
    ≈ USD 146 as all of Stages 1b/1c.
- **Architecture reconciliation (A-7f).** `docs/architecture.md` gains a
  node-by-node built-versus-proposed table under the diagram. Step 10 of the
  decision loop now says the verifier produces only `complete` or
  `needs_replan` (`verify_completion` in `telecom_domain/domain.py`); the
  other three `CompletionOutcome` values have no producer. Also corrected:
  - "Training has not started" (Phase 03C trained);
  - the Slow Reasoner (scripted by default; hosted only in direct model
    mode);
  - the Fast model paragraph (the 03C result and the local opt-in backend);
  - the State Ownership rows for object storage and MLflow (target, not
    built);
  - `voice/worker` (a placeholder);
  - Observability (what is built; no OpenTelemetry);
  - the Integrated Portfolio Demo list;
  - what the Data and Training Flow actually ran.
- **README.**
  - New sections: "Reproduce the simulator benchmark", "Observed versus
    proposed" (the product's real order, D9, and a stage-by-stage table
    against the 2026-09-21 proposal), and "What is not done".
  - The ML section adds the product-path negative result with its sources.
    It no longer says the runtime runs the untuned model; the default Fast
    is scripted.
  - The mailbox arrow no longer says "signed" (audit C-6). The same word is
    fixed twice in `docs/portfolio-demo.md`.
- **`docs/limitations.md` (new).** One page for every not-done item,
  negative result, measurement boundary and still-open recorded limit,
  grouped, each with its source, plus the cost table. It is a separate page,
  not a README section, because the limits span ML, the Runtime, the durable
  lane, the Web, the evaluation code and the gates; a README section that
  long would bury the overview. The README keeps a short not-done list and
  links the page.
- **`PLANS.md`.** A Phase 03C row (it had none) and the Phase 07 row.
- **`docs/README.md`.** It links `limitations.md`. Phase 03C moves from
  "Prepared, not activated" to the completed table, and Phase 07 is listed as
  in progress.

## Fresh-clone reproduction (DoD 4)

Run on 2026-09-25 (UTC 02:10–02:18) on the development machine: Apple M4
Pro, macOS 26.5.1, uv 0.8.4, pnpm 10.31.0, Node 22.15.1, Python 3.12.10,
Docker 28.3.2. The clone was in a scratch directory outside every worktree,
and the steps followed the README only.

| Step | Command | Wall time | Result |
|---|---|---|---|
| clone | `git clone --branch feat/pr16-phase07-contract https://github.com/SimondXu/ProxyLoop.git` | 63 s | exit 0, HEAD `ecfef63` |
| install | `pnpm install --frozen-lockfile` | 3 s | exit 0; 438 packages, all reused from the local pnpm store (0 downloaded); a warning that the build scripts of `sharp` and `unrs-resolver` were ignored, with no effect on the checks |
| gate | `make preflight` | 347 s | exit 0. `uv run` created `runtime/.venv` (52 packages) and `ml/.venv` (20) from the local uv cache, with no explicit `uv sync`. Runtime 2113 passed, 66 skipped; ML 498 passed, 1 skipped (`test_phase03c_training.py:360`: `yaml`, an optional extra, is not installed); vitest 268 passed; the Web build passed; the lock, compile and Compose checks passed; "Gated-skip counts match the pinned 66 per file" |
| benchmark check | `make benchmark-check` | 1 s | exit 0: "Phase 01B benchmark artifacts and ceiling gate are valid." |
| regenerate | `make benchmark` | < 1 s | exit 0; 32 scenarios, 32 valid outcomes, 10 completed, 0 false completions, 0 leakage violations, `gate_passed: true` |
| byte check | `git diff --exit-code`, on the two `data/manifests/phase-01b-*.json` and then on the whole tree | — | exit 0 both times; `git status --porcelain` was empty before and after |

This record is for `ecfef63`, which pins 66 gated skips; `main` pins 67
since #104, and the merged head's checks are recorded below.

These wall times are for a warm machine: the pnpm store and the uv cache
already held every package, so nothing was downloaded. A machine without
those caches downloads them first and takes longer. The ML tests were the
largest part of `make preflight` (204 s).

Doc gaps found and fixed:

1. The README did not say how to reproduce the simulator benchmark, and
   DoD 4 requires following only the README. The new section "Reproduce the
   simulator benchmark" names the commands above and the expected report
   values.
2. The README's Development block ran `make preflight` without
   `pnpm install --frozen-lockfile`, which the Web checks inside it need.
   Both places now include it.
3. The README did not say that `make preflight` needs the Docker CLI
   (`docker compose config --quiet`) but starts no container, or that `uv`
   creates the environments itself. It now does.

Not run here, by design: the three real-dependency gates and every Compose
demo scene. They need the shared DB/Temporal lane and run at the phase gate
(below).

## Cost figures, checked against their sources

The table in `docs/limitations.md` ("Cost") cites each figure's file.

- **≈ USD 146**, real relay usage for all Phase 03C Stage 1b/1c runs:
  `harness/log/phase-03c-stage1c-full-generation.md` ("real relay usage
  across all Stage 1b/1c runs ≈ USD 146") and
  `harness/context/phase-03c-stage2-handoff.md` §5.
- **USD 121.59**, the v6 full generation run alone, accounted:
  `phase-03c-teacher-generation-report.json` (`ledger.total_estimated_usd`
  121.5926, ceiling 140.0) and the Stage 1c log's run table.
  `harness/context/post-phase-03c-handoff.md` §4 calls USD 121.59 the "real
  relay usage over Stages 1b/1c". That conflicts with the primary log, and
  the docs follow the primary log.
- **Modal USD 22.25** for the phase (≈ USD 18.09 for the run, USD 4.16 for
  smokes and probes), billed USD 0.00: `harness/log/phase-03c-stage2-stage3.md`.
  `post-phase-03c-handoff.md` §4 agrees.
- **Phase 03A1 relay estimates:** r1 ≈ USD 1.58 (the sum of the conditions'
  `actual_cost_microusd`), r4 ≈ USD 3.11, r5 ≈ USD 0.117; r2 had one hosted
  failure of unknown cost. So ≈ USD 146 covers Phase 03C only, not the
  programme's whole relay spend.
- **Local compute:** one Apple M4 Pro; no dollar cost is recorded.

## DoD 1 closure table (draft for the root's inspection)

Blocking and Important audit findings, and the Important R-items, each
closed by a merged PR. The sources are `harness/context/audit-remediation-status.md`
§2–§4a and the logs it names.

| Findings (audit §3 group) | Severity | Closed by |
|---|---|---|
| B2-1, C-1; B2-2, C-2 | Blocking; Important | #38 |
| B1-1, B1-2 | Important | #39 |
| B2-4, E-4 | Important | #66 |
| C-3 | Important | #40 (P0-3b follow-up #46) |
| E-1, E-2, E-3 | Important | #43 |
| E-5, E-6 | Important | #63 |
| D2-1, D3-3 (claim); D2-4, F-1 | Blocking; Important | #44 (claims corrected, r5 reworded) |
| C-6 | Important | #44; residual "signed" wording closed in PR-17 |
| D2-5, D2-2 | Important | #48, #59 |
| B1-5/D1-2, B1-4, D1-7 | Important | #47 |
| D1-3, D1-4, D2-3 | Important | #49 |
| D1-1, D3-1, D3-2 | Important | #50 |
| B1-3 | Important | #54 |
| B2-3 | Important | #56 |
| D1-5, D1-6, D1-8 | Important | #64, #67, #60 |
| A-1, A-2 (with A-6, A-10, Minor or Note) | Important | #65, #68, #70, #72, #91 |
| A-4 (central to the demo claim) | Minor as a defect | #94, #95 |
| R-1, R-10, R-12, R-16 | Important | #78, #75, #91, #87 |
| R-17, R-18 (named by DoD 1) | — | #92, #88 |

The remaining Minors are closed or recorded as limits with a reason. Each is
in `docs/limitations.md`.

| Item | State | Reason |
|---|---|---|
| A-7f | closed by this PR | the docs now match `verify_completion` |
| R-11b, B1-9b | recorded limit | decision 21 dropped contracts 1.2 (PR-15) |
| R-6 | injectable offer TTL closed by #104; the pre-#61 one-day-manifest half stays a recorded limit | no migration of persisted Cases (A-11 log, `fix-r6-injectable-offer-ttl.md`) |
| D2-7, D2-8, D2-9 | recorded limit | the code is in frozen r2–r5 files, and the values are committed report bytes |
| D3-5, D3-6 | recorded limit | `qwen_mlx.py` is frozen by the r4 execution contract |
| D3-7 | accept-gap fixed (#74); field deletion recorded | the field is emitted in the committed trajectory schema |
| D3-8, D3-9 | recorded limit | frozen modules or committed report bytes would move |
| D1-10, D1-11, D1-12 | recorded limit | the V1 simulator is frozen, and V2 supersedes it |
| A-3, A-5, A-9 | recorded limit (#83); A-3 is also checked at Slow admission since PR-13 | the contract changes stay separate decisions |
| R-4, R-9, R-13 (retention), audit N1 | recorded limit | a frozen ML compiler; a shared test DB run serially; pruning is a policy decision; a frozen pipeline fallback |
| G-1 follow-up | recorded limit | the real-dependency gates do not themselves require zero gated skips |
| C-5 residual | recorded limit | host services can be orphaned by a signal during spawn (`fix-pr5-ops-tests.md`) |
| audit lane E, N5 | recorded limit | the Web has no reject control |

DoD 1 is verified by root inspection, so the root must confirm this table
against the primary evidence. Not checked here: each PR's merge commit.

## PR-17 checks (no `PROXYLOOP_TEST_*` set)

On the branch before the merge (base `ecfef63`):

- `make check-layout`, `make lint`: exit 0.
- `make test`: exit 0. Runtime 2113 passed, 66 skipped; ML 498 passed,
  1 skipped; every artifact check current, including `ops-report-check`.
- `make preflight`: exit 0 (341 s); vitest 268; "Gated-skip counts match the
  pinned 66 per file".
- The tests that read the edited docs
  (`tests/contract/test_phase_03a0_architecture.py`,
  `test_phase_03a1_architecture.py`,
  `test_phase_03a1_hosted_rerun_architecture.py`,
  `tests/integration/test_contract_semantics_limits.py`): 22 passed.

On the merged head (`origin/main` @ `abd1027` merged; the tree differs from
`main` only in PR-17's docs and harness files):

- `make check-layout`, `make lint`: exit 0.
- `make test`: exit 0 (324 s). Runtime 2150 passed, 67 skipped; ML 498
  passed, 1 skipped; every artifact check current, including
  `ops-report-check`.
- `make preflight`: exit 0 (352 s); vitest 269 passed; the Web build passed;
  "Gated-skip counts match the pinned 67 per file".
- This section was edited after that run; `make preflight-fast` covers it.

Not run: the three real-dependency gates, the demo scenes, CI.

## Phase gate (not run; runs at the gate)

The contract's phase-gate procedure runs on PR-17's final head once it is up
to date with `origin/main` (PR-16 merged). In one fresh worktree, after
`pnpm install --frozen-lockfile`, with the demo stopped, run one at a time:
`make preflight`, `make postgres-check`, `make phase05a-check`,
`make phase06b1-check`. Then CI and the independent review, then the squash
merge and the tree-identity check on `git rev-parse origin/main^{tree}`. The
final commit sets `harness/status.toml` back to `idle`.

## Independent review (PR-17): Request Changes, no Blocking

The root accepted every finding; all are applied.

- **I-1.** The M2 latencies are derivable from the committed
  `product-path-report.json` (`arms.<arm>.generated_rows[*].generation_ms`
  and `.wall_ms`); the earlier "per-row files are not committed" sentence
  was wrong. Recomputed from that file: distilled median 23,928 ms, max
  32,544 ms, 64/200 over 25 s by `generation_ms` (65 by `wall_ms`); untuned
  median 10,429 ms, max 12,872 ms. `docs/ml-evidence.md`,
  `docs/limitations.md` and the README cite the file.
- **M-1.** "8/8 succeeded and were withheld" now reads "returned output and
  were rejected by the gate (trace `rejected` 8; fallback cause `gate` 8)",
  checked against both split reports.
- **M-2.** C-6: "#44; residual wording closed in PR-17".
- **M-3.** Status-file rows B1-9 → #81, G-1 → #90 (pin now 67), R-15 → #90.
- **M-4.** The README's dialogue row reads "0/240 delivered: 40 refused
  before the model, 200/200 gated outputs withheld".
- **M-5.** The architecture table gains the Consumer/Provider/Channel Event
  node and the two contract nodes (`FastTurnDecision` `contracts.py:738`;
  `SlowWorkResult` `:1464` and `StrategyPacket` `:302`).
- **M-6.** Data and Training Flow: step 2's real status (a license gate that
  has admitted only the project's synthetic source), and the Phase 03C gaps
  against step 11 (one seed, no paired Fast/Slow baselines, held out by
  family only, with both provider configurations in the held-out rows).
- **M-7.** README prerequisites: `python3` 3.11 or newer (`tomllib`), the
  Compose v2 plugin, and the CI pins (uv 0.8.4, Node 22.15.1, Python 3.12.10
  from `.github/workflows/ci.yml`; pnpm 10.31.0 from `package.json`).
- **M-8.** The cost table states in its first row that its rows are not
  additive.
- **M-9.** Edits outside the contract's PR-17 file list, each authorised by
  the root: `docs/portfolio-demo.md` (the C-6 residual "signed"), the
  build-plan PR-17 row and the `post-phase-03c-handoff.md` correction note
  (decision 1), the decision-17 correction note, and the final pass on
  `harness/context/audit-remediation-status.md` (decision 3). `docs/README.md`
  gained the limitations link and the 03C and 07 rows.
- **Nit.** The README's design bullet says Slow is scripted and a hosted
  reasoner is possible only in opt-in direct model mode.

## Open for the root (PR-17)

- Resolved (root decision 2): PR-16 amended the contract for the #103
  non-goal (amendment A3). After the merge, `docs/limitations.md` says the
  restore is done by #103 and is no longer a non-goal.
- Resolved (root decision 1, 2026-09-25): follow the primary logs. The
  build plan's PR-17 row is corrected, and `post-phase-03c-handoff.md` §4
  gains a dated correction note; its original sentence stays. Decision 17 in
  `audit-remediation-decisions.md` gets the same dated note (root-authorised),
  appended after its original text.
- Done (root decision 3, scope extension): the final pass on
  `harness/context/audit-remediation-status.md` closes A-7f, replaces the
  stale in-flight table with the merged PRs #87–#105 (PR-17 pending), and
  marks R-5, R-6, R-12, R-13b, R-17, R-19 and A-3 done with their PRs.
- Resolved by the merge of `origin/main` @ `abd1027`: #104 closed the
  offer-TTL half of R-6 and raised the gated-skip pin from 66 to 67. The
  fresh-clone record above is for `ecfef63` and keeps 66, which that head
  pins; the checks on the merged head below show 67.
