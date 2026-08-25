# Local Web demo UI

This is a bounded conversation-first interface for one local fictional
telecom journey. The conversation remains the main workspace; structured Task
Brief, Progress, Offer, Approval, and Evidence receipt artifacts appear inline.

The UI is connected only to `runtime/services/api` through the rewrite in
`apps/web/next.config.ts` and the narrow client in `apps/web/lib/runtime-client.ts`.
It does not add a BFF, state-management framework, model call, login, real
Provider, account action, persistence, workflow engine, channel, voice path,
deployment, or production Pine clone claim.

The demo creates a Case from the Runtime, derives the displayed facts from the
returned Case/snapshot, sends one consumer event only after the user confirms
the hotspot and device-financing constraint, and sends approval with the exact
revision values returned in the pending response. A receipt is marked
Verified only when the Runtime says `complete`, execution count is one, and
every returned completion Evidence ID matches an Evidence item in that same
response.

See [research.md](research.md) for the evidence boundary, [user-flows.md](user-flows.md)
for the journey, and [state-matrix.md](state-matrix.md) for fail-closed states.
