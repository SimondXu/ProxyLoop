# Minimal local Web demo

**Status**: Local implementation and independent review complete on
`feat/minimal-local-web-demo`. PR #18 passed CI/GitGuardian and Sol approved it
for squash merge.

## Objective

Restore the useful conversation-first structure of the local Pine-inspired
snapshot and connect exactly one local fictional-telecom journey to the
authoritative Thin Runtime API. The Web layer must show Runtime-derived Case
facts, ask for one material constraint confirmation, wait for an exact approval,
and render a receipt only when deterministic completion Evidence is verifiable.

## Frozen boundaries

- Conversation is the only primary workspace. Keep the calm three-column,
  inline-artifact, responsive presentation language from snapshot `b8d7ee5`.
- `apps/web/next.config.ts` is the only rewrite seam and maps
  `/api/runtime/:path*` to `http://127.0.0.1:8000/:path*`.
- `apps/web/lib/runtime-client.ts` is the only Web-to-Runtime client seam.
- Use only `POST /cases`, `POST /cases/{case_id}/events`, and
  `POST /cases/{case_id}/approvals/{approval_id}` from the existing API.
- The UI never reads `.env`, credentials, or external model services; it does
  not add a BFF, generic API framework, state-management library, retry
  framework, real Provider, authentication, channels, voice, deployment,
  persistence, workflow durability, training, or evaluation work.
- Do not restore the snapshot's static `demo-case.ts` or `/cases/demo*` flow.
- The blank composer accepts a Case-creation request only when a small readable
  lexical gate finds independent telecom, billing-context, and explicit
  reduction-outcome terms. Unsupported first messages remain local and explain
  the one supported demo; this gate is not general natural-language or
  multilingual support.
- Runtime-derived Task Brief and pending Approval views use small explicit
  predicates for Money, required string constraints, exact approval pins,
  material hash/expiry, and the first offer's provider, price, term, and
  features. Missing facts block the journey and never expose a confirm or
  approval action.
- Each create, event, and approval request is bound to a monotonic conversation
  session id. Restart invalidates late responses and clears busy state.
- Approval must pass the exact waiting payload `revision`,
  `approval.case_revision`, `approval.action_intent_revision`, and
  `approval_id` through unchanged.
- HTTP 409/503, network failure, malformed/non-JSON payload, unsupported
  corrections, and terminal-but-unverified responses remain visible blocked or
  retry/restart states. They never become success.
- A receipt is Verified only if completion is `complete`, execution count is
  `1`, completion Evidence IDs are non-empty, and every ID matches returned
  Evidence.

## Acceptance criteria

1. The root Web route is a conversation-first responsive shell with inline Task
   Brief, Progress, Offer, Approval, and Evidence receipt artifacts.
2. The Case and Task Brief facts are derived from the Runtime response; the
   user must confirm hotspot and device financing before the sole consumer
   event is sent. Unsupported first requests do not call `POST /cases` and
   remain in the blank conversation with a retry explanation.
3. The happy path creates a Case, sends one event, reaches pending approval,
   approves using exact returned pins, and renders a verified receipt only when
   the receipt predicate passes.
4. Client and UI tests cover happy path, exact pins, malformed/409/503/network
   failures, malformed Task Brief/offer fail-closed behavior, stale-response
   restart behavior, and no-matching-Evidence fail-closed behavior.
5. Docs state the private-page observation boundary, snapshot reuse audit, and
   local fictional-Provider-only scope.

## Verification

Run from the repository root without downloading dependencies:

```text
pnpm install --lockfile-only --ignore-scripts --offline
make web-check
git diff --check
make preflight
```

Record actual outcomes in `harness/build-log.md`. Browser, live Runtime
server, external model/provider, auth, cloud, and deployment checks remain
separate and must not be implied by this contract.
