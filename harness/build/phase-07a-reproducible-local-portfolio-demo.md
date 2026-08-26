# Phase 07A Reproducible Local Portfolio Demo

## Authorization

Phase 07A is an explicitly approved, bounded early subphase of Phase 07
Portfolio Hardening. It packages already integrated local behavior into a
reproducible portfolio demonstration. It does not complete Phase 06 or the
full Phase 07 roadmap and does not authorize Phase 06B2, Gmail, Voice, model
loading/calls, deployment, or any real external effect.

## Baseline and problem

The integrated baseline at `17f6585` already contains the conversation-first
Web flow, a Runtime-owned Case, PostgreSQL authority, Temporal command
ordering/waits/retries, revision-bound approval, recovery, authoritative
completion Evidence, and the synthetic `local_mailbox`. Those parts have
focused tests but no one reliable local startup path, no runnable portfolio
scenario, and no current operator narrative that distinguishes implemented,
locally verified, proposed, deferred, and failed research results.

## Objective

Provide one credential-free local startup contract and two truthful demo
scenes that a reviewer can reproduce on a clean checkout:

1. **Web Case scene** — use the existing Web conversation to collect the four
   telecom facts, create the Runtime-owned Case, surface the exact approval,
   execute once after approval, recover through PostgreSQL/Temporal, and show
   completion only from authoritative Evidence.
2. **Controlled channel scene** — use a command-line fixture driver against
   the API-only `local_mailbox` boundary to prove raw-byte verification,
   server-owned Case correlation, one PostgreSQL inbox/outbox identity,
   Temporal delivery, duplicate replay safety, an authoritative delivery
   observation, and browser-projection isolation.

They are intentionally separate scenes. The Web does not invoke or render the
channel route, and a completed Web Case is terminal for further channel work.
No narration may present the two scenes as one Web-driven end-to-end journey.

## Frozen startup contract

- Add one primary `make portfolio-demo` target. It must start the existing
  Compose PostgreSQL/Temporal server dependencies, then the host workflow worker,
  FastAPI Runtime in explicit scripted/PostgreSQL/Temporal mode, and the
  existing Next.js Web app.
- A small repository script may supervise the processes, readiness checks,
  signal handling, diagnostics, and cleanup. Do not containerize the Python or
  Web applications and do not add a general service manager.
- Use only loopback endpoints, repository fixture credentials for local
  PostgreSQL, the deterministic scripted Runtime, and the synthetic mailbox.
  The startup path must fail closed if dependencies or ports are unavailable;
  it must not fall back to memory/direct/model modes.
- Provide a bounded stop command and an explicit reset command for only the
  demo's isolated named local Compose resources. Normal stop preserves PostgreSQL data;
  reset may delete only the demo volume and must print that scope before doing
  so.
- Startup output must list the Web URL, Runtime readiness URL, and Temporal server address,
  the exact two-scene order, log locations, and how to stop. It must never print
  credentials, request signatures, raw mailbox bodies, or arbitrary exception
  payloads.

## Frozen scene and evidence rules

### Scene A — Web Case

- Preserve the existing UI, route structure, four-fact intake, browser
  envelope, polling, recovery, approval pins, and completion predicate.
- The four facts are current monthly total, target monthly total, hotspot
  requirement, and device-financing-change prohibition.
- The expected end state is one Runtime-owned Case, one approved exact action,
  one fictional Provider execution, `completion.decision == complete`, and the
  top-level simulator-transition/confirmation Evidence required by the
  existing Web receipt predicate.
- Manual Browser verification must cover normal completion plus one API or
  worker restart/reconnect observation, at desktop and mobile widths, without
  horizontal overflow or new console warnings/errors.

### Scene B — synthetic `local_mailbox`

- Provide one deterministic command or script that operates on a fresh/reset
  demo state and creates the same four-fact scripted Case through Runtime
  commands before posting the signed raw-byte fixture.
- The script may display the API's existing synthetic channel response fields
  and compact, allowlisted PostgreSQL assertions for the operator. It must not
  add them to Web storage, Web requests, the browser Case payload, or a new
  browser/API inspection route.
- Assert one server-correlated inbox event, one outbox/delivery identity, an
  accepted synthetic Provider reference, exact duplicate deduplication, one
  delivered callback/receipt, and authoritative Provider-message/event
  Evidence. Assert separately that the browser Case projection contains no
  channel content, provider reference, channel artifact hash, or channel-only
  Evidence.
- The scenario must label synthetic acceptance and delivery honestly. It does
  not prove real-provider delivery, production exactly-once effects, or
  production readiness.

### Recovery evidence

- A reproducible focused command must use real local PostgreSQL and Temporal to
  demonstrate at least worker restart while a command is waiting or mailbox
  lost-response/idempotent recovery. Reuse the accepted Phase 05A/06B1 fault
  paths where possible; do not invent a production monitoring layer.
- PostgreSQL remains the only business truth; Temporal owns ordering, waits,
  retries, workflow history, and recovery references.

## Documentation and portfolio evidence

- Update the root README with prerequisites, `make portfolio-demo`, the two
  scenes, reset/stop/recovery commands, expected results, troubleshooting, and
  observed-versus-deferred boundaries.
- Update `PLANS.md`, `docs/architecture.md`, and `harness/status.toml` without
  marking Phase 06, Phase 06B2, or full Phase 07 complete.
- Record 2–4 evidence-backed resume bullet drafts, a 2–3 minute demo narration,
  limitations/negative results, and the unchanged Phase 03B
  `NO_GO_STOP_PHASE03B`. Bullets remain drafts until their stated local checks
  pass and must not claim production scale, real channels, promoted models, or
  exactly-once external effects.
- Name the future Gmail seam at the API verification/channel adapter boundary
  and the future Voice seam at the deferred LiveKit/SIP channel worker. Both
  remain proposed/unauthorized and require separate policy, credential,
  security, retention, and evaluation gates.

## Acceptance criteria

1. `make portfolio-demo` starts PostgreSQL, Temporal, workflow worker, FastAPI
   Runtime, and Web with explicit deterministic configuration and bounded
   readiness diagnostics; Ctrl-C/stop terminates host processes safely.
2. A fresh reviewer can follow the documented prerequisites and commands
   without credentials, model downloads/calls, Gmail, Voice, or external
   Provider access.
3. Scene A completes the existing four-intake, exact-approval, one-execution,
   PostgreSQL/Temporal, and authoritative-Evidence flow with no product-flow or
   visual redesign.
4. Scene B is repeatable on a fresh/reset state and machine-checks Case
   creation, verified inbound, duplicate deduplication, one outbox/delivery
   identity, synthetic acceptance, delivered callback, channel Evidence, and
   browser-projection isolation.
5. A documented focused recovery command proves a real local worker-restart or
   lost-response recovery path while preserving one logical command/effect.
6. Normal stop preserves local Case data and documented restart confirms
   PostgreSQL-backed recovery. Explicit reset affects only named demo Compose
   data and produces a fresh scenario.
7. No Web source, browser envelope, or browser-facing Runtime schema gains
   mailbox content, provider references, artifact hashes, signatures, or
   channel-only Evidence.
8. Focused automated checks cover the new supervisor/scenario behavior and all
   changed Make/documented command contracts. Existing Phase 05A, Phase 06A,
   Phase 06B1, and Web behavior remain compatible.
9. Browser/manual verification covers Scene A, restart/reconnect behavior,
   desktop/mobile layout, console state, and observed expected results.
10. README, PLANS, architecture, portfolio narrative, Harness log, and final
    status clearly separate implemented, locally verified, proposed/deferred,
    unverified, and failed/No-Go evidence.
11. Fresh independent Terra review has no unresolved Blocking, Important, or
    Minor finding. Root Sol inspects the complete diff and primary evidence.
12. Focused checks pass, then one stable-diff `make preflight` passes. Hosted
    phase-gate and GitGuardian pass on the final PR head before squash merge.
13. The bounded execution log records exact checks, Browser evidence, review,
    known gaps, and integration state. After merge, Harness returns to idle
    with Phase 06B2 Gmail, Voice, ML rerun/promotion, deployment, and release
    still unauthorized/deferred.

## Explicitly out of scope

- Gmail API, Gmail OAuth, tokens, real inboxes, real Provider contact, MCP, SMS,
  or any other external channel;
- LiveKit, SIP, phone numbers, telephony, ASR/TTS, Voice implementation, or
  audio persistence;
- consumer authentication, account linking, multi-tenancy, deployment,
  hosting, release, production monitoring, production capacity, production
  exactly-once, or production-readiness claims;
- real model loading/calls, model promotion, Phase 03 retraining, data
  expansion, rerun, or promotion;
- canonical contract/evaluator changes, arbitrary channel messages, channel
  exposure in Web, unrelated architecture refactors, or UI redesign.

## Ownership and verification

- Root Sol owns this contract/status, architecture and startup boundaries,
  browser/channel isolation, acceptance semantics, scope, final diff/evidence
  review, integration, and every completion claim.
- One Luna xhigh implementer may own the bounded startup/scenario/test/doc
  implementation after this contract is frozen. It may not change this
  contract, Harness status, security boundaries, canonical contracts,
  completion semantics, or phase scope; commit, push, merge; use credentials or
  real external systems; or start another phase.
- One fresh Terra high reviewer performs read-only defect-first review after
  the material diff is stable. Accepted findings return to the same
  implementer unless they touch a Sol-retained boundary.

## Stop conditions

Stop and request a new user decision only if completion requires credentials,
real external access/effects, Gmail/Voice/model integration, destructive work
outside the named local demo resources, canonical contract/security changes,
deployment/release, or scope beyond Phase 07A. Ordinary implementation and
local fixture/recovery decisions continue from repository evidence.
