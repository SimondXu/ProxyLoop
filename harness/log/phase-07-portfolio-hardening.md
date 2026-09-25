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

Nothing under `runtime/`, and none of the hot files, changed. No committed
`*-check` artifact moved, and the gated-skip pin is unchanged at 66.

## Finding F1 (escalated to the root)

The contract's Scene J expects that "every journey request has one JSON
operation record in the Runtime log". This cannot be observed.

- `JsonLoggingOperationRecorder` logs at INFO to `proxyloop_api.operations`.
- `proxyloop_api/server.py` runs uvicorn with `log_level="error"` and attaches
  no handler to that logger. INFO records therefore fall through to Python's
  last-resort handler, which prints WARNING and above only.
- A local probe confirmed it: a direct-mode server on port 8123 answered
  `POST /intake/proposals` and `GET /health/ready`, and wrote nothing to its
  output.

Making the check pass needs a change to `runtime/services/api` (a handler in
`server.py`), which is outside the contract's frozen scope. The
operation-record assertion is therefore not implemented. The ops report says
"not reported" for operation records, and `docs/architecture.md` states the
limit. The root's options are (a) amend the contract to drop the check, or
(b) authorize a small logging-handler change in `server.py`, which would also
need the DB gates.

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

## Checks (PR-16 head before commit)

- `make lint`: exit 0 (the first run failed on 5 E501 errors; ruff format
  fixed them).
- `make typecheck`: exit 0 (79 and 70 source files; `scripts/run_ops_report.py`
  added to the mypy list).
- `make test`: exit 0. Runtime 2109 passed, 66 skipped. ML 498 passed,
  1 skipped. `ops-report.json is current`.
- `make web-check`: exit 0. vitest 262 passed, and the build passed. The
  `outputFileTracingRoot` multiple-lockfiles warning comes from the worktree
  sitting inside the main checkout.
- `make preflight`: exit 0. Gated skips were 66 and matched the per-file pin.

## Needs the lane (not run)

The DB and Compose lane is required, so none of these were run. The DB gates
were not run, and no `PROXYLOOP_TEST_*` variable was set.

- Scene 0 on the real stack.
- Scene A in the Browser, at desktop and mobile widths.
- Scene J, then `WRITE_EVIDENCE=1`, then `make ops-report`, then committing
  both artifacts.
- Scene A-D, a manual run with the distilled backend.
- Scene B.
- Scene R.
- `make postgres-check`, `make phase05a-check` and `make phase06b1-check`,
  run serially.
