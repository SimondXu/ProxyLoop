# Portfolio demo (Phase 07A, extended in Phase 07)

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
make portfolio-demo                                  # Runtime 8000, Web 3000
make portfolio-demo RUNTIME_PORT=8011 WEB_PORT=3011  # explicit other ports
```

starts the Compose PostgreSQL and Temporal server (project name
`proxyloop-portfolio-demo`, PostgreSQL on 55433, Temporal on 7234), then the
host workflow worker, the FastAPI Runtime, and a production build of the
Next.js Web app. Startup prints the Web URL, Runtime readiness URL, Temporal
address, Fast backend, log directory, stop command, and the scene order.
`RUNTIME_PORT` and `WEB_PORT` (Phase 07) are explicit loopback overrides: a
port that is taken, out of range, equal to the other, or reserved for the
demo's PostgreSQL/Temporal/recovery services makes the command fail closed
before anything starts; the launcher never picks another port. The Web's
Runtime rewrite follows `RUNTIME_PORT` through `PROXYLOOP_RUNTIME_ORIGIN`, which
`apps/web/next.config.ts` accepts only as an `http://127.0.0.1:port` or
`http://localhost:port` origin; the destination is fixed at build time.
The scene commands take the same `RUNTIME_PORT`.

The demo Case has a fixed id, so every scene starts from fresh state: run
`make portfolio-demo-stop`, then `make portfolio-demo-reset` (it prints its
scope, then removes only the `proxyloop-portfolio-demo_postgres-data`
volume), then `make portfolio-demo` again.

### Scene A — the Web journey, in the order the product runs it

1. **Intake.** Describe the bill in one message, for example "My mobile bill
   is $92 and I want to get it under $75. Keep my hotspot." The stateless
   intake reads it into the Draft Task Brief card: "$92.00", "$75.00", and
   hotspot "Required", each "Read from your message"; the missing financing
   fact is asked for, and Create stays disabled until it is answered. After
   "no change" the row reads "Confirmed · unchanged". The words are never
   stored or logged.
2. **Create.** "Create fictional Case" sends only the confirmed typed facts.
   Inside that one command the fictional Offer arrives, Slow proposes it (the
   Standing Proposal, admitted by the A-3 check), and a scripted Judge reviews
   that Slow result. The Judge is advisory and invisible in the Web: it
   appears only as a `role=judge` Model Trace, and on the default scripted
   Slow it always accepts, so its revise-and-retry path runs only in tests.
   The Status Bar reads "Waiting for you to confirm the Task Brief." at Case
   revision 2, because the workspace now waits for the constraint
   confirmation below.
3. **Confirmation turn.** "Keep both unchanged and continue" is the consumer
   turn. It gets exactly one Assistant Message, "Thanks. I'm reviewing the
   fictional offer against your constraints now.", labelled "ProxyLoop AI ·
   automated message — it cannot accept, sign, or change anything without
   your approval.", and it opens the exact Approval Request from the Standing
   Proposal. The Status Bar reads "Waiting for your approval of the exact
   terms." with the same expiry as the approval card (revision 4).
4. **Approve.** "Approve exact terms" executes once against the fictional
   Provider. The Status Bar reads "Done: the Runtime verified completion
   against Provider Evidence.", "Executed 1 time", and "Verified complete · 1
   matching Evidence ID · receipt shown" (revision 6), and the receipt appears
   only after the Evidence predicate passes.
5. **Reload.** The same Case, execution count, and receipt come back from
   PostgreSQL/Temporal.

The Status Bar sits in the context rail, which is hidden below 1120 px.

### Scene J — the scripted journey driver (Phase 07)

From a second terminal, on fresh state, run `make portfolio-demo-journey`. It
drives the same HTTP routes the Web uses, in the same order: intake with a
marker message, create from the returned typed facts plus the financing
answer, the Web's confirmation text, the approval, an exact replay of the
approval with the same `Idempotency-Key`, and a final read. It asserts that
three facts were read and one was asked for; that the confirmation produced
exactly the offer, the consumer turn, and one Assistant Message (the first
scripted line on the scripted backend) and a pending approval; that the
execution count is 1 after the approval and still 1 after the replay, with the
revision unchanged; that the Web's receipt predicate holds; that the
PostgreSQL Model Trace log for the Case holds exactly one `slow`, one `judge`,
and one `fast` trace, all `succeeded` (no Judge retry); that `runtime.log`
gained exactly one content-free operation record per journey request, all
with error category `none`; and that the marker is absent from the proposal
response and the Runtime, worker, and Web logs. Close the Web tab first:
nothing else may call the Runtime during Scene J.
`make portfolio-demo-journey WRITE_EVIDENCE=1` also writes the committed,
content-free `data/evaluation/phase-07-demo-journey-scripted.json` (scripted
backend only).

### Scene B — synthetic `local_mailbox` (unchanged from 07A)

From a second terminal, on fresh state, run `make portfolio-demo-channel`. It
creates a fresh scripted Case, posts the SHA-256-fingerprinted raw-byte `local_mailbox`
fixture, replays it exactly, observes one accepted synthetic delivery, posts
the delivered callback, and verifies browser-projection isolation from
PostgreSQL authority.

Expected Scene B results: one server-correlated inbox identity, one outbox
delivery identity, exact duplicate deduplication, one accepted synthetic
Provider reference, one delivered callback/receipt, two authoritative channel
Evidence records, and no channel content, provider reference, or artifact hash
in the browser Case projection.

### Recovery, stop, and the operations report

`make portfolio-demo-stop` is bounded and preserves PostgreSQL data.
`make portfolio-demo-recovery` reuses the accepted Phase 06B1
lost-response/idempotent retry path against PostgreSQL and Temporal; it needs
the primary Temporal service from `make portfolio-demo` and creates and stops
only the temporary `postgres-test` service.

`make ops-report` (Phase 07) needs no running service, credential, or network.
It reads only committed files and writes `data/evaluation/ops-report.json`:
the `make test` check inventory, the three real-dependency gates with their
collected test counts (their pass counts come only from the recorded serial
gate run), the gated-skip pin, the scripted, distilled, and untuned split
reports (the local two marked pre-Judge), the M1 and M2 parity headlines,
trace health invariants, the Scene J evidence once recorded, and what is not
measured or not done. `make ops-report-check` is part of `make test`.

### Opt-in local Fast backend (PR-11)

```text
FAST_BACKEND=distilled make portfolio-demo    # or FAST_BACKEND=untuned
```

runs the same demo with the Temporal worker's Fast turns served by the local
Phase 03C model gateway: `distilled` is the Local Opt-in Candidate, `untuned`
the untuned local baseline; the default `FAST_BACKEND=scripted` is the demo
above. The launcher does not start the gateway. Start it first in its own
terminal with PR-9b's `make local-fast-gateway BACKEND=distilled` (Apple
silicon, the cached base model, about 17 GB of memory). If the gateway's
default port 8765 is taken, pick another with `LOCAL_FAST_PORT=<port>` and
start the demo with `PROXYLOOP_FAST_GATEWAY_URL=http://127.0.0.1:<port>`
set as well. `serve` probes its
`/v1/identity` before it starts Compose or any host process and refuses with
that command in the message if the gateway is absent or serves another
backend. The flag sets `PROXYLOOP_FAST_BACKEND` for the worker and the API
alike, overriding any value inherited from the shell; the start banner prints
the backend and its label.

What changes: each consumer turn in Scene A gets the gate-passed model line
or the fixed fallback line ("I am checking that and will update you."), and
its Fast trace names the local model and gateway identity; the approval, the
single execution, and the receipt are unchanged because Fast cannot change
routing. Since #103 the Web also restores the Case after a reload on the
local backends (under Temporal and PostgreSQL). PR-9 expects the distilled line to be withheld and replaced
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
`make portfolio-demo-stop` before retrying. A port held by an unrelated
process is never stopped by the demo; choose other ports with `RUNTIME_PORT=`
and `WEB_PORT=` instead. If Scene J or Scene B reports that state is not
fresh, stop/reset, restart `make portfolio-demo`, and rerun the scene.
If `make portfolio-demo-stop` refuses because a stale `pids.json` names PIDs
that now belong to other processes, delete
`$TMPDIR/proxyloop-portfolio-demo/pids.json` by hand.

## Demo narration

First, I start `make portfolio-demo`. The supervisor starts the existing local
PostgreSQL and Temporal server dependencies, then the host worker, the
scripted PostgreSQL-backed Runtime, and the existing Next.js Web. It prints
readiness information, bounded log locations, and the scene order.

In Scene A, I describe my bill in one message. The intake reads it into a
typed card and asks only for the fact it could not read; nothing is stored
until I confirm. When I create the Case, the fictional Offer arrives, the
scripted Slow proposes it, and a scripted Judge reviews that proposal; the
Judge is advisory and shows up only in the Model Traces. My confirmation turn
gets one automated assistant line that passed the Disclosure Gate, and it
opens the exact approval, which the Status Bar mirrors. I approve, the Runtime
executes once, and the receipt is shown only after the authoritative Evidence
predicate passes. I then reload and confirm the Case is recovered from
PostgreSQL/Temporal without changing the Web flow.

After a reset, Scene J replays the same journey through the Web's HTTP routes
from a script, adds an exact approval replay that does not execute again, and
checks the Model Trace log: one Slow, one Judge, and one Fast trace.

I stop and reset the local state before Scene B because the scenes are
intentionally independent, then restart the stack and wait for readiness. The channel driver creates the same four-fact Case
through the Runtime API, posts a SHA-256-fingerprinted synthetic raw-byte Provider message,
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
- The Judge is scripted and advisory. On the default scripted Slow it always
  accepts, so the revise-and-retry path is exercised only in tests; the demo
  shows the Judge as one trace per admitted Slow result, never a quality
  effect or a verdict distribution.
- The Web has exactly one consumer dialogue turn after creation (the
  confirmation). Multi-turn dialogue is measured by the split report's
  `dialogue_path`, not shown in the Web.
- In the Phase 07A run, Browser completion passed locally at 1280x900 and
  375x812 without horizontal overflow or warning/error console output. After a bounded stop and restart
  that preserved the isolated PostgreSQL volume, the Web recovered the same
  verified Case, single execution, and authoritative Evidence receipt.
- The unchanged Phase 03B decision is `NO_GO_STOP_PHASE03B`; Phase 07A does not
  authorize retraining, data expansion, reruns, or promotion.

Not done, and not claimed anywhere in this demo:

- production of any kind: production serving of the distilled adapter,
  real-model load, p95, capacity, concurrency, OOM, automatic fallback under
  load, production exactly-once effects, production monitoring, and
  production readiness;
- deployment, hosting, and release;
- Phase 06B2 and every real channel (real Providers, Gmail/OAuth, e-mail, MCP,
  SMS, Voice) and every credential;
- V0, frontier-as-Fast, and a second-family Judge (not measured, budget);
- a model Judge and any Judge verdict distribution;
- further training, data expansion, reruns, or promotion;
- narrow contracts 1.2 (dropped by decision 21);
- the build-plan "Do not do" list (D3-5, D3-6, D1-10 to D1-12, D2-7 to D2-9,
  D3-7 to D3-9, A-9b, and a `SlowWorkRequest.revision_feedback` field);
- a Web free-text turn after Case creation, Web exposure of channels or the
  Judge, and any UI redesign;
- hosted spend of any kind.

The future Gmail seam is proposed at the API verification/channel-adapter
boundary. The future Voice seam is proposed at the deferred LiveKit/SIP
channel worker. Each requires separate policy, credential, security,
retention, and evaluation gates.
