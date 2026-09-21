# Infrastructure

Local infrastructure is defined in the root `compose.yaml`. The `infra/`
subdirectories (`compose/`, `migrations/`, `observability/`, `temporal/`) are
reserved placeholders and currently contain only `.gitkeep`; PostgreSQL schema
setup lives in `runtime/packages/case_runtime` and Temporal namespace setup
uses the `temporalio/auto-setup` image.

Compose services:

- `postgres` — persistent local PostgreSQL 17 used by the Phase 04C/05A/06B1
  Runtime profile and by `make portfolio-demo` (project name
  `proxyloop-portfolio-demo`, volume `proxyloop-portfolio-demo_postgres-data`).
- `temporal` and `temporal-ui` — Temporal server (auto-setup) and UI for the
  Phase 05A `CaseWorkflow`, Phase 06B1 mailbox dispatch, and the portfolio demo.
- `postgres-test` — profile-gated, disposable PostgreSQL 17 instance for the
  integration gates. It binds port `55432` by default, uses the
  `proxyloop_test` database, and stores data in tmpfs with no persistent
  volume:

```text
docker compose --profile postgres-test up -d postgres-test
```

Set `PROXYLOOP_TEST_DATABASE_URL` to that database URL before running
`make postgres-check`, `make phase05a-check`, or `make phase06b1-check`. The
test suite refuses to clean or inspect any database whose name is not exactly
`proxyloop_test`. Hosted CI provisions equivalent PostgreSQL and Temporal
services directly in `.github/workflows/ci.yml`.

`make preflight` only validates the Compose file (`docker compose config`);
it does not start any container.
