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
make validate                Format, lint, mypy, tests, contract drift, layout
make preflight               validate + lock checks + Compose config (the CI gate)
make format / format-check   Ruff format
make lint / typecheck        Ruff lint / strict mypy
make unit-test / test        Runtime and ML pytest
make web-check               Web lint, typecheck, vitest, production build
make contracts               Regenerate JSON Schema and TypeScript contracts
make contracts-check         Verify generated artifacts and compile the TS fixture
make simulator               Emit the Phase 01A success episode as JSON
make benchmark / -check      Phase 01B scripted environment-ceiling report
make data-pilot / -check     Phase 02 one-turn pilot report and drift check
make harness / harness-check Phase 03A1 deterministic evaluation harness
make baselines-check         Phase 03A1 untuned baseline artifacts
make errata / errata-check   Phase 03A1 evaluation erratum artifacts
make hosted-rerun-check      Source-bound Phase 03A1 r4 hosted report
make validity-smoke-check    Source-bound Phase 03A1 r5 diagnostic report
make phase03b-readiness-check / phase03b-experiment-check
                             Frozen Phase 03B readiness and smoke artifacts
make postgres-check          Phase 04C PostgreSQL gate (needs postgres-test)
make phase04d-check / phase04d-profile-check
                             Phase 04D control-plane gates
make phase05a-check          Phase 05A Temporal CaseWorkflow gate
make phase06b1-check         Phase 06B1 local mailbox gate
make runtime-server / dev    Scripted Runtime on 127.0.0.1:8000
make portfolio-demo[-stop|-reset|-channel|-recovery]
                             Phase 07A local demo lifecycle
```

The `*-check` artifact targets replay committed reports with zero external
model calls. `postgres-check`, `phase05a-check`, and `phase06b1-check` need
`PROXYLOOP_TEST_DATABASE_URL` pointing at the `proxyloop_test` database and,
for the last two, a reachable Temporal server.

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
