# Applications

`web/` is a bounded local Next.js conversation demo. It uses the existing
FastAPI Thin Runtime through one `/api/runtime/*` rewrite and one narrow
client module. The journey is intentionally limited to the fictional telecom
Case: a consumer clearly describes lowering a mobile bill, confirms that
hotspot and device financing stay unchanged, reviews one Runtime offer,
approves its exact pins, and receives a verifier-backed Evidence receipt.
Unsupported first messages remain local with a scope explanation; the small
English lexical gate is not general language understanding.

Run the Runtime and Web processes separately:

```text
make runtime-server
pnpm --filter @proxyloop/web dev
```

The Web layer does not add authentication, a generic BFF, model calls, real
Providers, persistence, workflow durability, or static demo completion data.
Its local journey is a bounded implementation slice, not a production UI or a
Pine clone claim.
