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
    `http://{127.0.0.1|localhost|[::1]}:port`, with no path, query or
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

## Open for the root

- Amendment A2, the Status Bar text after create, needs the root's
  confirmation.
- Independent review of PR-16 and the PR itself are not started.
