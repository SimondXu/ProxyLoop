# Local Web demo UI

This is a bounded conversation-first interface for one local fictional
telecom journey. The conversation remains the main workspace; structured Task
Brief, Progress, Offer, Approval, and Evidence receipt artifacts appear inline.

The UI is connected only to `runtime/services/api` through the rewrite in
`apps/web/next.config.ts` and the narrow client in `apps/web/lib/runtime-client.ts`.
It does not add a BFF, state-management framework, model call, login, real
Provider, account action, workflow engine, channel, voice path,
deployment, or production Pine clone claim.

The demo first collects the current bill, target bill, required mobile hotspot,
and forbidden financing change in a local Draft Task Brief. It does not call
the Runtime while the brief is incomplete or merely drafted. One explicit
`Create fictional Case` action sends exactly those four facts to the API-local
intake boundary. The Runtime then owns the canonical Case; the Web verifies
both the root Case and nested snapshot against the confirmed draft before
showing the verified Task Brief. It sends one consumer event only after the
user confirms the hotspot and device-financing constraint, and sends approval
with the exact revision values returned in the pending response. A receipt is marked
Verified only when the Runtime says `complete`, execution count is one, and
every returned completion Evidence ID matches an Evidence item in an
authoritative GET response after the approval command.

After Case creation, confirmed intake facts are immutable in this local demo.
The browser stores only a versioned Case locator, those four facts, and at most
one exact pending command for safe retry; it does not persist the transcript.
Reload recovery is claimed only when readiness reports scripted Temporal and
PostgreSQL. Changing one requires restarting the local Runtime and choosing
`New task`; there is no PATCH or second-Case mutation path.

See [research.md](research.md) for the evidence boundary, [user-flows.md](user-flows.md)
for the journey, and [state-matrix.md](state-matrix.md) for fail-closed states.
