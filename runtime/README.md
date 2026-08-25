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
