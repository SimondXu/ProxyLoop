# Infrastructure

`compose.yaml` provisions local PostgreSQL and Temporal for later integration work. It is not required for the Phase 0 layout validation.

The `postgres-test` Compose profile is a disposable PostgreSQL 17 instance for
the Phase 04C integration gate. It binds port `55432` by default, uses the
`proxyloop_test` database, and stores data in tmpfs with no persistent volume:

```text
docker compose --profile postgres-test up -d postgres-test
```

Set `PROXYLOOP_TEST_DATABASE_URL` to that database URL before running
`make postgres-check`. The test suite refuses to clean or inspect any database
whose name is not exactly `proxyloop_test`.
