# Applications

`web/` is a bounded local Next.js conversation demo. It uses the existing
FastAPI Thin Runtime through one `/api/runtime/*` rewrite and one narrow
client module. The journey is intentionally limited to the fictional telecom
Case: a consumer clearly describes lowering a mobile bill, confirms that
hotspot and device financing stay unchanged, reviews one Runtime offer,
approves its exact pins, and receives a verifier-backed Evidence receipt.
Unsupported first messages remain local with a scope explanation; the small
English lexical gate is not general language understanding.

Run the Runtime and Web processes separately for iterative work. This direct
mode, in its default in-memory configuration, holds one Case per Runtime
process, ignores
`Idempotency-Key`, and cannot resume a Case after a page reload; use
`make portfolio-demo` for the durable profile:

```text
make runtime-server
pnpm --filter @proxyloop/web dev
```

For the full durable stack (Compose PostgreSQL and Temporal, workflow worker,
Runtime, production Web build) use `make portfolio-demo`; see
[`docs/portfolio-demo.md`](../docs/portfolio-demo.md). `make web-check` runs
lint, typecheck, vitest, and the production build.

The Web layer does not add authentication, a generic BFF, model calls, real
Providers, authoritative Case persistence, or a workflow engine. The browser
stores only a versioned local locator, confirmed facts, and one exact pending
command for retry; durable recovery still requires the existing Temporal and
PostgreSQL Runtime profile. It does not provide workflow durability itself or
static demo completion data. Its local journey is a bounded implementation
slice, not a production UI or a Pine clone claim.
