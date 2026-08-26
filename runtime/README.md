# Runtime

This uv workspace contains the canonical contracts, the fictional Provider
simulator, and the local Thin Agent Runtime. The default server mode is
scripted and stays in memory:

```text
make runtime-server
```

The command binds `127.0.0.1:8000` and exposes the local Case HTTP flow. Model
mode is an explicit opt-in and requires process configuration for
`PROXYLOOP_MODEL_API_KEY`, `PROXYLOOP_MODEL_BASE_URL`, and
`PROXYLOOP_MODEL_NAME`; the server never loads `.env` files. Automated tests
inject a fake transport and do not call an external model.

Storage is independently selected with `PROXYLOOP_STORAGE_MODE=memory` (the
default) or `PROXYLOOP_STORAGE_MODE=postgres`. PostgreSQL mode requires a
non-empty `PROXYLOOP_DATABASE_URL` and persists one strict, versioned Case
aggregate with revision compare-and-swap. Model selection remains independent
of storage selection.

The local control plane exposes `GET /health/live` for process-only liveness and
`GET /health/ready` for a memory check or PostgreSQL `SELECT 1`. It emits one
allowlisted operation record per Case or health request through non-retaining JSON
structured logging by default, without request bodies, prompts, credentials,
database URLs, headers, or exception text. Tests may inject an in-memory recorder.
The Phase 04D diagnostic profile is credential-free and local-only:

```text
make phase04d-profile-check
```

The profile is diagnostic evidence, not a production capacity, real-model
latency, OOM, autoscaling, or promoted-serving claim.

The disposable integration gate requires an explicit test-only database URL:

```text
docker compose --profile postgres-test up -d postgres-test
PROXYLOOP_TEST_DATABASE_URL=postgresql://proxyloop:proxyloop@127.0.0.1:55432/proxyloop_test make postgres-check
```

The check refuses to run without `PROXYLOOP_TEST_DATABASE_URL`; it verifies
that the connected database is exactly `proxyloop_test` before cleaning test
rows.
