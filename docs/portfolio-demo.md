# Phase 07A portfolio evidence

This page is the evidence-backed portfolio narrative for the bounded local
demo. The resume bullets remain wording drafts; their named local checks and
independent review passed.

## Resume bullet drafts

- Draft: Built a deterministic, credential-free consumer telecom Case flow with
  FastAPI, PostgreSQL authority, Temporal command ordering, approval pins, and
  authoritative completion Evidence. Evidence command: `make portfolio-demo`
  plus the existing Web/manual completion and restart checks.
- Draft: Added an API-only synthetic `local_mailbox` scene that verifies exact
  raw-byte authenticity, server-owned Case correlation, PostgreSQL inbox/outbox
  identity, duplicate replay deduplication, delivery receipt persistence, and
  browser projection isolation. Evidence sequence: stop/reset, restart
  `make portfolio-demo`, then run `make portfolio-demo-channel` from a second
  terminal.
- Draft: Reused the Phase 06B1 Temporal lost-response path to demonstrate local
  idempotent delivery recovery while keeping PostgreSQL as business truth.
  Evidence command: `make portfolio-demo-recovery` with the primary local
  Temporal service running.

These drafts do not claim production scale, real-channel delivery, promoted
models, or exactly-once external effects.

## Demo narration

First, I start `make portfolio-demo`. The supervisor starts the existing local
PostgreSQL and Temporal server dependencies, then the host worker, the
scripted PostgreSQL-backed Runtime, and the existing Next.js Web. It prints
readiness information, bounded log locations, and the two-scene order.

In Scene A, I use the conversation workspace to provide the current monthly
total, target monthly total, mobile-hotspot requirement, and device-financing
prohibition. The Runtime creates one Case, proposes the fictional offer, waits
for the exact approval pins, and executes once after approval. The receipt is
shown only after the existing authoritative Evidence predicate passes. I then
observe a restart/reconnect check and confirm the Case is recovered from
PostgreSQL/Temporal without changing the Web flow.

I stop and reset the local state before Scene B because the scenes are
intentionally independent, then restart the stack and wait for readiness. The channel driver creates the same four-fact Case
through the Runtime API, posts a signed synthetic raw-byte Provider message,
replays the exact fixture, and checks one deduplicated inbox identity and one
outbox delivery identity through the existing PostgreSQL seam. It posts the
synthetic delivered callback, checks one receipt and the Provider-message/event
Evidence, and separately reads the normal Case endpoint to prove the browser
projection has no channel material. Finally, I describe the result honestly as
local synthetic acceptance and delivery, not real-provider delivery.

## Limitations and negative results

- The local mailbox is a fixture adapter. Gmail, OAuth, credentials, real
  inboxes, real Provider contact, MCP, SMS, LiveKit, SIP, and voice persistence
  remain unauthorized.
- The scripted Runtime is deterministic. No model is downloaded or called,
  and no model promotion, serving-capacity, or production-readiness result is
  implied.
- PostgreSQL/Temporal recovery is a local fault-path observation. It does not
  establish production exactly-once external effects or production capacity.
- Browser completion passed locally at 1280x900 and 375x812 without horizontal
  overflow or warning/error console output. After a bounded stop and restart
  that preserved the isolated PostgreSQL volume, the Web recovered the same
  verified Case, single execution, and authoritative Evidence receipt.
- The unchanged Phase 03B decision is `NO_GO_STOP_PHASE03B`; Phase 07A does not
  authorize retraining, data expansion, reruns, or promotion.

The future Gmail seam is proposed at the API verification/channel-adapter
boundary. The future Voice seam is proposed at the deferred LiveKit/SIP
channel worker. Each requires separate policy, credential, security,
retention, and evaluation gates.
