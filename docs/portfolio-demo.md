# Portfolio demo (Phase 07A)

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

## Running the demo

Prerequisites are Docker with Compose, `uv`, `pnpm`, and the repository's
installed dependencies. The demo uses only loopback ports, the repository's
local PostgreSQL fixture credentials, the deterministic scripted Runtime, the
synthetic mailbox, and the fictional Provider simulator. By default it does
not download or call a model (the opt-in local Fast backend below calls a
cached local one), and it never contacts Gmail, Voice, or an external
Provider.

```text
make portfolio-demo
```

starts the Compose PostgreSQL and Temporal server (project name
`proxyloop-portfolio-demo`), then the host workflow worker, the FastAPI
Runtime, and a production build of the Next.js Web app. Startup prints the Web
URL, Runtime readiness URL, Temporal address, log directory, stop command, and
the fixed scene order. In the reference run the services bound PostgreSQL on
55433, Temporal on 7234, Runtime on 8000, and Web on 3000.

1. **Scene A** — use the Web conversation to confirm the four telecom facts,
   approve the exact offer, and observe one fictional Provider execution and
   authoritative completion Evidence.
2. Stop and reset (`make portfolio-demo-reset`), then restart
   `make portfolio-demo` so Scene B starts from fresh state. Reset prints its
   scope before removing only the `proxyloop-portfolio-demo_postgres-data`
   volume.
3. **Scene B** — from a second terminal run `make portfolio-demo-channel`. It
   creates a fresh scripted Case, posts the signed raw-byte `local_mailbox`
   fixture, replays it exactly, observes one accepted synthetic delivery,
   posts the delivered callback, and verifies browser-projection isolation
   from PostgreSQL authority.

Expected Scene B results: one server-correlated inbox identity, one outbox
delivery identity, exact duplicate deduplication, one accepted synthetic
Provider reference, one delivered callback/receipt, two authoritative channel
Evidence records, and no channel content, provider reference, or artifact hash
in the browser Case projection.

`make portfolio-demo-stop` is bounded and preserves PostgreSQL data.
`make portfolio-demo-recovery` reuses the accepted Phase 06B1
lost-response/idempotent retry path against PostgreSQL and Temporal; it needs
the primary Temporal service from `make portfolio-demo` and creates and stops
only the temporary `postgres-test` service.

### Opt-in local Fast backend (PR-11)

```text
FAST_BACKEND=distilled make portfolio-demo    # or FAST_BACKEND=untuned
```

runs the same demo with the Temporal worker's Fast turns served by the local
Phase 03C model gateway: `distilled` is the Local Opt-in Candidate, `untuned`
the untuned local baseline; the default `FAST_BACKEND=scripted` is the demo
above. The launcher does not start the gateway. Start it first in its own
terminal with PR-9b's `make local-fast-gateway BACKEND=distilled` (Apple
silicon, the cached base model, about 17 GB of memory); `serve` probes its
`/v1/identity` before it starts Compose or any host process and refuses with
that command in the message if the gateway is absent or serves another
backend. The flag sets `PROXYLOOP_FAST_BACKEND` for the worker and the API
alike, overriding any value inherited from the shell; the start banner prints
the backend and its label.

What changes: each consumer turn in Scene A gets the gate-passed model line
or the fixed fallback line, and its Fast trace names the local model and
gateway identity. PR-9 expects the distilled line to be withheld and replaced
by the fallback on nearly every turn; that is the measured result, not a
fault. A Fast call can take up to 25 s (the timeout); a timeout, a busy
gateway, or a gateway that stops mid-demo delivers the fallback and the Case
continues. Scene B is unchanged: channel commands keep the scripted Fast, so
the synthetic outbound body stays the constant line and no model is called.
The recovery check is unchanged. This is a local opt-in run on one machine:
no latency, capacity, or quality claim, and the gateway has no
authentication.

Troubleshooting: if startup reports an unavailable port or dependency, inspect
the printed log directory and
`docker compose --project-name proxyloop-portfolio-demo ps`, then run
`make portfolio-demo-stop` before retrying. If Scene B reports that state is
not fresh, stop/reset, restart `make portfolio-demo`, and rerun Scene B.
If `make portfolio-demo-stop` refuses because a stale `pids.json` names PIDs
that now belong to other processes, delete
`$TMPDIR/proxyloop-portfolio-demo/pids.json` by hand.

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
- The scripted Runtime is deterministic. By default no model is downloaded or
  called; with `FAST_BACKEND=distilled|untuned` only the already-cached local
  model behind the loopback gateway is called, for Fast turns only. No model
  promotion, serving-capacity, or production-readiness result is implied.
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
