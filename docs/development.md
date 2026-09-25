# Development guide

Operational detail that used to live in the root README. The README is the
reader-facing overview; this file is for people changing the code.

## Environments

The repository is a polyglot monorepo with isolated dependency zones
([ADR](decisions/2026-08-21-monorepo.md)):

- `runtime/` — Python 3.12 `uv` workspace (`uv sync --all-packages` inside
  `runtime/`). Contains every package and service the demo runs.
- `ml/` — separate Python 3.12 `uv` project for data, evaluation, and
  experiment runners. It is not imported by the Runtime.
- `apps/web/` — Next.js app in the root `pnpm` workspace
  (`pnpm install --frozen-lockfile` at the root).
- Root `compose.yaml` — local PostgreSQL 17, Temporal (auto-setup) and
  Temporal UI, plus a profile-gated disposable `postgres-test`
  ([infra/README.md](../infra/README.md)).

## Make targets

```text
make preflight-fast          Layout, script syntax, and Git whitespace checks
make validate                format-check, lint, typecheck, test, check-layout,
                             web-check
make preflight               validate + lock-check + script compile + Compose
                             config + pinned gated-skip count (see "Local gate
                             and real-dependency gates")
make format / format-check   Ruff format
make lint / typecheck        Ruff lint / strict mypy
make unit-test               Runtime and ML pytest
make test                    unit-test plus the artifact checks listed after
                             `test:` in the Makefile
make web-check               Web lint, typecheck, vitest, production build
make contracts               Regenerate JSON Schema and TypeScript contracts
make contracts-check         Regenerate into a temp dir, byte-compare with the
                             committed artifacts, compile the TS fixture
make simulator               Emit the Phase 01A success episode as JSON
make benchmark / -check      Phase 01B scripted environment ceiling; -check
                             re-runs it, byte-compares, fails on a failed gate
make negotiation-check       V2 negotiation ceiling: re-runs the reference
                             consumer over the catalogue, byte-compares
                             data/manifests/negotiation-v1-ceiling.json, fails
                             on drift or a failed gate
make data-pilot / -check     Phase 02 pilot; -check regenerates, byte-compares,
                             fails unless the automated audit passed
make harness / harness-check Phase 03A1 harness; -check generates twice
                             (determinism), byte-compares manifest, episodes
                             and ceiling, fails on a failed ceiling gate
make baselines-check         r1 legacy replay through the current evaluator;
                             fails on the current tree by design (the Harness
                             episodes were regenerated after r1); not in `test`
make baselines-historical-check
                             r1 integrity only (fingerprints, provenance,
                             truthfulness), no replay; reports the episode
                             drift as a state instead of failing
make errata / errata-check   Phase 03A1-E; -check regenerates and compares the
                             r2 fixtures, checks the r2 report's fingerprints,
                             replays r3 from its captured raw outputs, and
                             binds r3 to r2
make hosted-rerun-check      Alias: depends on hosted-rescore-check only (the
                             r4-era `hosted_rerun --check` is not in `test`)
make hosted-rescore          r4 integrity check, then write
                             data/evaluation/phase-03a1-r4-rescored-report.json
                             by re-reading the r4 raw outputs with the current
                             evaluator (no model calls)
make hosted-rescore-check    r4 integrity; prints whether the r4 execution
                             bytes changed (reported, never a failure); fails
                             unless the committed rescored report equals a
                             fresh derivation byte for byte
make validity-smoke-check    Phase 03A1-V r5: binds to r4 by hash and replays
                             every row from its stored raw outputs
make phase03b-readiness-check
                             Regenerate the Gate 0 packet and byte-compare
make phase03b-experiment-check
                             Re-derive train/valid rows, manifest and QLoRA
                             config (Phase 02 provenance fields as recorded);
                             bind each smoke arm to the committed manifest
make phase03c-rescore-check  Re-score the stored Phase 03C cloud raw outputs
                             (held-out and dev) with the repository evaluator,
                             byte-compare the committed *-rescored.json, fail
                             on any disagreement with the cloud scores; exits 0
                             with a notice when no cloud run is present
make postgres-check          Phase 04C PostgreSQL gate (needs postgres-test)
make phase04d-check          Phase 04D control-plane operation tests
make phase04d-profile-check  Phase 04D profile: fresh report compared with
                             the shape baseline committed in the script
                             (keys, types, exact counts and rates) plus
                             p95 >= p50; no timing thresholds
make phase05a-check          Phase 05A Temporal CaseWorkflow gate
make phase06b1-check         Phase 06B1 local mailbox gate
make runtime-server / dev    Scripted Runtime on 127.0.0.1:8000
make portfolio-demo[-stop|-reset|-channel|-recovery]
                             Phase 07A local demo lifecycle
```

The artifact checks make zero external model calls, but they prove different
things. `contracts-check`, `benchmark-check`, `negotiation-check`,
`data-pilot-check`, `harness-check`, and `phase03b-readiness-check` regenerate
their artifacts from code and byte-compare them. `errata-check`,
`validity-smoke-check`, `hosted-rescore-check`, and `phase03c-rescore-check`
re-derive scores from stored raw model outputs with the current evaluator.
`baselines-historical-check` checks integrity only. `baselines-check` fails
by design. The other `phase03c-*` checks in the `test:` list are not
described here; see the Makefile.

## Local gate and real-dependency gates

`make preflight` runs `validate` (`format-check`, `lint`, `typecheck`, `test`,
`check-layout`, `web-check`), then `lock-check`,
`python3 -m compileall -q scripts`, `docker compose config --quiet`, and
last `scripts/check_gated_skips.py`. It starts no container.

`unit-test` collects all of `tests/integration`. Six files skip their
database tests when `PROXYLOOP_TEST_DATABASE_URL` is unset; their Temporal
tests also need `PROXYLOOP_TEST_TEMPORAL_ADDRESS`:

- `test_fast_under_temporal.py` (3: time-skipping Workflow tests on an
  in-memory repository, gated on `PROXYLOOP_TEST_TEMPORAL_ADDRESS` alone
  like the re-drive test below; run in `phase05a-check`)
- `test_phase_04c_persistent_case_store.py` (29 tests)
- `test_phase_05a_case_runtime.py` (2)
- `test_phase_05a_temporal_workflow.py` (24)
- `test_phase_06b1_channel_runtime.py` (4: three through a fixture imported
  from `test_phase_06b1_temporal.py`, and the time-skipping re-drive test,
  gated on `PROXYLOOP_TEST_TEMPORAL_ADDRESS` alone so `make test` never
  starts the Temporal test server)
- `test_phase_06b1_temporal.py` (4)

With the variables unset, `make preflight` exits 0 and skips those 66 tests,
so a "preflight passed" claim covers none of them. `unit-test` writes the
runtime pytest JUnit report to `.gate/runtime-junit.xml` (git-ignored); the
last preflight step counts the tests skipped with a `PROXYLOOP_TEST_*` reason,
prints the count per file, and names the three real-dependency targets below.
The count is pinned per file (`EXPECTED_GATED_SKIPS_PER_FILE` in
`scripts/check_gated_skips.py`): a test that newly skips on a missing
variable, or a gated test that is removed, added, or moved between files,
fails preflight until the pin and this list change together. Only
`PROXYLOOP_TEST_DATABASE_URL` and `PROXYLOOP_TEST_TEMPORAL_ADDRESS` decide
enforcement (other `PROXYLOOP_TEST_*` names are ignored): with neither set
the pin is enforced; with both set no gated test may skip; with exactly one
set `unit-test` runs the gated tests it can reach and the count is printed
but not enforced. A change under
`case_runtime`, `workflow_worker`, `connectors`, or `api` therefore also needs
the real-dependency gates below.

The real-dependency gates fail instead of skipping when a variable is missing:

| Target | Needs | Runs |
|---|---|---|
| `postgres-check` | `PROXYLOOP_TEST_DATABASE_URL` | `test_phase_04c_persistent_case_store.py` |
| `phase05a-check` | `PROXYLOOP_TEST_DATABASE_URL`, `PROXYLOOP_TEST_TEMPORAL_ADDRESS` | `test_phase_05a_case_runtime.py`, `test_phase_05a_temporal_api.py`, `test_phase_05a_temporal_workflow.py`, `test_fast_under_temporal.py` |
| `phase06b1-check` | `PROXYLOOP_TEST_DATABASE_URL`, `PROXYLOOP_TEST_TEMPORAL_ADDRESS` | `test_phase_06b1_connectors.py`, `test_phase_06b1_channel_runtime.py`, `test_phase_06b1_workflow_worker.py`, `test_phase_06b1_temporal.py` |

`PROXYLOOP_TEST_DATABASE_URL` must name the `proxyloop_test` database; the
tests refuse any other name. Locally that is the `postgres-test` Compose
profile on port `55432` ([infra/README.md](../infra/README.md)).
`PROXYLOOP_TEST_TEMPORAL_ADDRESS` is locally the Compose `temporal` service at
`127.0.0.1:7233` by default (`TEMPORAL_PORT` overrides the port); CI sets it to
`127.0.0.1:7233`.

Run these gates one at a time, from one worktree at a time. The tests
truncate their tables in the shared `proxyloop_test` database and reuse fixed
ids (the scripted Case id and fixed command UUIDs), so two concurrent runs
truncate each other's rows and fail intermittently (`case_not_found`,
`state_invalid`). A `make preflight` with the variables set is such a run.

## Hosted CI

`.github/workflows/ci.yml` runs one job, `phase-gate`, on every PR: it
provisions PostgreSQL 17 and Temporal as services, installs `uv`, Node 22 and
pnpm, then runs `make preflight`, `make postgres-check`, `make phase04d-check`,
`make phase04d-profile-check`, `make phase05a-check`, and
`make phase06b1-check`. The Phase 07A `portfolio-demo*` targets are local-only
and are not exercised in CI.

## Running the Runtime by hand

```text
make runtime-server
```

binds the scripted Runtime to `127.0.0.1:8000` with the in-memory Case
repository. Storage and orchestration modes are explicit and never fall back:

- `PROXYLOOP_STORAGE_MODE=postgres` plus a database URL enables the
  PostgreSQL aggregate store (Phase 04C).
- Temporal mode requires scripted decisions and PostgreSQL; see
  [runtime/README.md](../runtime/README.md).
- Model mode is opt-in and requires `PROXYLOOP_MODEL_API_KEY`,
  `PROXYLOOP_MODEL_BASE_URL`, and `PROXYLOOP_MODEL_NAME` in the process
  environment:

  ```text
  uv run --project runtime --all-packages python -m proxyloop_api.server --mode model
  ```

  The server does not load `.env` files. No real model smoke is part of the
  automated gate.
- A local Fast backend is opt-in, with scripted Runtime mode (Slow stays
  scripted), in direct mode or under Temporal (PR-11). Under Temporal the
  worker and the API read the same variables; start both with the same
  values (`FAST_BACKEND=distilled make portfolio-demo` does):

  | Variable | Values | Rule |
  |---|---|---|
  | `PROXYLOOP_FAST_BACKEND` | `scripted` (default), `distilled`, `untuned` | `distilled` is the Phase 03C Local Opt-in Candidate, `untuned` its base |
  | `PROXYLOOP_FAST_GATEWAY_URL` | default `http://127.0.0.1:8765` | an `http://` loopback origin only; the Runtime accepts `127.0.0.1`, `::1` and `localhost`, but PR-9b's gateway listens on IPv4 `127.0.0.1` only, so `http://[::1]:<port>` fails at startup (the identity probe cannot connect). Use `127.0.0.1` or `localhost` with the gateway's port (`make local-fast-gateway LOCAL_FAST_PORT=<port>`) |
  | `PROXYLOOP_FAST_TIMEOUT_S` | default `25` (the cap) | a number in [0.1, 25]; a distilled call can hold the direct-mode app lock for up to this long |

  The server, and under Temporal the worker, refuses to start unless the
  gateway answers `/v1/identity` with the selected backend. A failed Fast
  call delivers the fallback line and is traced `FAILED`; nothing retries or
  switches backend (under Temporal the activity completes, so it is not
  retried either). Channel commands keep scripted Fast and the constant
  outbound body. Roll back by
  setting `scripted` and restarting. The gateway process and its runbook are
  PR-9b's (`ml/serving/`); CI uses only the in-test fake gateway.

For the Web app alone, run `pnpm --filter @proxyloop/web dev` against a
running Runtime ([apps/README.md](../apps/README.md)).

## Phase-gated workflow

Work is organized as one explicitly approved phase at a time. Each phase has
an executable contract in `harness/build/`, an activation preflight in
`harness/context/`, an independent review in `harness/code_review/`, and a
concise execution log in `harness/log/`. `harness/status.toml` is the only
live authorization state; `PLANS.md` is the phase index. The lifecycle is
described in [harness/README.md](../harness/README.md); the Git workflow in
[CONTRIBUTING.md](../CONTRIBUTING.md); agent behavior in
[AGENTS.md](../AGENTS.md).

The repository was built with a Codex role split: Sol (high) for root
orchestration, Luna (xhigh) for clearly specified implementation, Terra (high)
for independent review, and Luna (medium) for narrow mechanical work. Model
choice never relaxes file ownership, safety, evidence, or phase-scope rules.

## Where things are

- Phase contracts, reviews, and logs, phase by phase:
  [docs/README.md](README.md#completed-phase-gates)
- Chronological delivery record: [planning/progress.md](planning/progress.md)
- Historical evidence before Harness v2: [harness/build-log.md](../harness/build-log.md)
