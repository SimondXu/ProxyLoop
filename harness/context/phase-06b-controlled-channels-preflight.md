# Phase 06B Controlled Channels Proposal / Preflight

**Date**: 2026-08-26

**Baseline**: clean synchronized `main` at `40e324f`

**Harness state**: `idle`; `next_phase_authorized = false`

**Decision owner**: root Sol

**Audit decision**: `GO_FOR_PHASE_PROPOSAL`

**Implementation gate**: `APPROVED_FOR_PHASE_06B1`

This began as a proposal-only artifact. On 2026-08-26 the user explicitly
approved the recommended route and requested execution under the repository's
subagent mechanism. The executable bounded contract is now
`harness/build/phase-06b1-local-controlled-mailbox.md`. That approval activates
only Phase 06B1; no real Provider, model, email, MCP, voice, credential,
deployment, release, or Phase 06B2 is authorized.

## Executive recommendation

Split Phase 06B into two explicit gates:

1. **Phase 06B1 — local controlled mailbox**: add one bidirectional,
   email-shaped but entirely local/fake asynchronous text channel. Use only
   synthetic identities, deterministic fixture authenticity, PostgreSQL
   inbox/outbox/receipt state, and Temporal activities. Preserve the existing
   conversation UI and all current HTTP behavior. This slice proves the
   channel authority, correlation, replay, idempotency, reconciliation, and
   Evidence rules without contacting any external system.
2. **Phase 06B2 — real controlled integration**: only after a separate user
   gate, select one real test channel, provider-specific webhook verifier,
   credential and retention design, and owned test endpoint/account. Start
   with a draft-only or controlled test-mailbox capability. Voice remains a
   later independent gate.

The first controlled channel should therefore be `local_mailbox`, not Gmail,
SMS, SIP, or LiveKit. It should exercise both inbound and outbound semantics;
an outbound-only fake would leave webhook authenticity, replay, duplicate
delivery, and Case correlation unverified.

`GO_FOR_PHASE_PROPOSAL` means the repository has enough reusable authority and
durability primitives to freeze a buildable 06B1 contract. It is not a Go for
implementation. Phase 06B remains inactive until the user approves the 06B1
scope and a separate `harness/build/` contract.

## Preserved behavior

The following are compatibility invariants, not redesign opportunities:

- the existing Pine-like conversation remains the primary Web workspace;
- the four confirmed intake facts and correction behavior remain unchanged;
- Phase 06A browser Case recovery, exact pending-command retry, readiness,
  GET-first reconciliation, monotonic revision/event-cursor checks, bounded
  visibility-aware polling, and final authoritative GET remain unchanged;
- the current Task Brief, Offer, exact Approval, pending execution/finalizing,
  completion, and Evidence receipt predicates remain unchanged;
- the Web continues to use only `/api/runtime/:path*` through
  `apps/web/lib/runtime-client.ts` and never receives channel credentials;
- the existing create/event/approval request and response shapes remain
  compatible. The channel ingress surface is separate and is not called by
  the Web;
- PostgreSQL remains authoritative for business and channel audit state;
  Temporal remains authoritative only for ordering, waits, retries, and
  recovery;
- models remain proposal-only. They cannot verify a webhook, select a Case
  binding, authorize a disclosure, send a message, create Evidence, or declare
  completion.

## Verified current capability inventory

| Capability | Verified current path | Current boundary |
|---|---|---|
| Conversation-first Web with four-fact intake | `apps/web/app/components/conversation-workspace.tsx`, `apps/web/app/components/conversation-workspace.test.tsx` | One fictional telecom Case; no channel surface. |
| Narrow Web-to-Runtime seam | `apps/web/lib/runtime-client.ts`, `apps/web/next.config.ts` | Existing Case POSTs, readiness, and GET only. Every existing POST can carry a browser-owned UUIDv4 idempotency key. |
| Durable Web recovery | Phase 06A Web code and 47 focused tests | Browser storage is only a strict Case locator plus one exact pending command. PostgreSQL remains authoritative. |
| Runtime control plane | `runtime/services/api/src/proxyloop_api/app.py` | Exposes health, Case create/read, one `consumer_message` event, and exact approval decision. It has no webhook route, channel identity, or provider delivery endpoint. |
| Redacted operation observation | `runtime/services/api/src/proxyloop_api/operations.py` | Allowlist-only operation records exclude request bodies and arbitrary headers. No channel outcome fields exist yet. |
| Temporal Case ordering | `runtime/services/workflow_worker/src/proxyloop_workflow_worker/{models,client,workflow,activities}.py` | Strictly supports create, `consumer_message`, approval decision, and approval expiry against one CaseWorkflow. It has no channel activity or callback command. |
| PostgreSQL Case authority and command receipts | `runtime/packages/case_runtime/src/proxyloop_case_runtime/{repository,postgres_repository,commands,runtime}.py` | One versioned JSONB Case aggregate with CAS and same-Case semantic command receipts. There is no inbox, outbox, channel binding, or delivery receipt table. |
| Current execution policy | `runtime/packages/agent_core/src/proxyloop_agent_core/capabilities.py` | Revalidates current pins, delegated authority, approval, expiry, capability, offer, and idempotency immediately before a simulator-only in-process prepare/commit. Its idempotency cache is process-local and is not suitable for real effects. |
| Generic domain vocabulary | `ActionType.SEND_MESSAGE`, `EvidenceType.PROVIDER_MESSAGE`, `EvidenceType.PROVIDER_EVENT`, `Evidence`, `VisibleCaseEvent`, and Delegated Authority in `runtime/packages/contracts` | Useful concepts already exist, but `CapabilityManifest`, `CapabilityReference`, and the adapter protocol are deliberately simulator-only. |
| Channel scaffolding | `runtime/packages/connectors/.gitkeep` | Placeholder only; no implemented adapter, interface, tests, or dependencies. |
| Voice scaffolding | `voice/README.md`, `voice/worker/.gitkeep` | Placeholder only; explicitly deferred. |
| Architectural invariants | `docs/architecture.md` Durable Orchestration, State Ownership, Agent Decision Loop, and Safety and Reliability Invariants | External inputs are untrusted; real effects require outbox, provider event ID when available, and idempotency. No real-effect exactly-once claim exists. |

## Gaps and user/safety impact

| Gap | Why it matters |
|---|---|
| No server-owned channel binding | A sender-controlled `case_id`, address, or thread reference could route an untrusted event into the wrong Case. |
| No raw-body authenticity seam | Parsing before verification can make signature checks ambiguous and cannot support provider-specific verification later. |
| No global inbox/replay ledger | Case-local command receipts cannot safely deduplicate a callback before its Case is known, nor detect one external event ID reused with different bytes. |
| No atomic Case-plus-outbox write | Scheduling a send in Temporal history or process memory can lose a send after a crash or send without a matching authoritative Case record. |
| Simulator-specific synchronous executor | `prepare()` plus in-process `commit()` does not model an external request whose response can be lost, accepted but not delivered, or reconciled later. |
| No delivery lifecycle | HTTP/provider acceptance, delivery, bounce, and terminal failure are materially different states. Treating any one as completion would create false Evidence. |
| Simulator-only Capability Manifest | A channel operation cannot be advertised or authorized through the current canonical capability interface without an explicit contract evolution. |
| No PII/retention policy for channel artifacts | Real addresses, headers, bodies, recordings, or transcripts could leak into Case state, logs, browser storage, or training exports. |
| No channel-specific observability allowlist | Logging raw webhook errors, signatures, addresses, or message bodies would violate the current redaction boundary. |
| No provider-specific reconciliation | A timeout after send cannot prove whether the provider accepted the message. Blind retry could duplicate an external effect. |

## Alternatives

### Option A — bidirectional local mailbox, then a separately gated real adapter

Build one local/fake asynchronous text mailbox with valid/invalid authenticity
fixtures, inbound replay, outbound outbox dispatch, provider acknowledgement,
delivery callbacks, and fault injection. Store only synthetic identities and
redacted/hashed artifacts.

**Advantages**:

- validates every high-risk semantic before credentials or network calls;
- exercises inbound and outbound correlation, replay, idempotency, outbox,
  reconciliation, delivery receipt, and Evidence provenance;
- keeps the current conversation UI and product flow unchanged;
- creates a deep channel seam that a later real adapter can satisfy.

**Costs**:

- requires new private PostgreSQL channel state and atomic mutation support;
- requires a separate ingress route and Temporal channel activity;
- requires a deliberate capability-contract evolution or an explicit decision
  not to expose channel sends to models in 06B1.

**Recommendation**: select this option for Phase 06B1.

### Option B — outbound-only local draft adapter

Persist an outbound draft/outbox and deliver it to a local mailbox, but accept
no inbound event.

**Advantages**:

- smallest implementation and no webhook surface;
- proves durable authorization-before-dispatch and basic reconciliation.

**Costs**:

- does not verify authenticity, replay, duplicate callback, inbound identity,
  or Case-correlation behavior;
- creates a shallow first seam likely to be redesigned when inbound support is
  added;
- does not meet the full Phase 06B preflight questions.

**Recommendation**: reject as the main 06B1 slice. It is acceptable only as a
short red test inside Option A, not as the phase boundary.

### Option C — Gmail or another real test provider first

Start with a real draft-only/test-mailbox provider and provider-specific OAuth,
webhooks, or polling.

**Advantages**:

- produces a recognizable external demo earlier;
- exposes real provider response and reconciliation behavior.

**Costs**:

- requires credentials, external network calls, provider-specific policy,
  account ownership, retention/deletion, and deployment decisions that are not
  authorized;
- couples the architecture to provider details before the authority and
  durability seam is proven;
- makes failures difficult to attribute between provider behavior and
  ProxyLoop semantics.

**Recommendation**: defer to Phase 06B2 behind a new explicit gate.

Voice-first is not a fourth viable 06B1 option. It adds telephony identity,
recording/disclosure, audio retention, interruption, latency, SIP/provider
credentials, and owned-number requirements before the text-channel safety seam
exists.

## Recommended Phase split

### Phase 06B1 — local controlled mailbox

The slice is complete only when one synthetic Provider-side local mailbox can
exchange bounded text events with an existing fictional Case through durable,
auditable state. It does not replace the fictional Provider simulator and does
not make channel delivery sufficient for Case completion.

Scope:

- one channel kind: `local_mailbox`;
- one synthetic channel binding to the existing scripted fictional Case;
- inbound raw-byte verification through a fake/local verifier adapter;
- server-owned identity/correlation, inbox replay ledger, and Case event
  projection;
- one bounded outbound `send_message` path using current Delegated Authority;
- PostgreSQL-authoritative outbox and delivery receipts;
- Temporal dispatch, retry, wait, and reconciliation using stable references;
- fake acceptance, lost-response, delayed-delivery, duplicate callback,
  retryable failure, and terminal-failure behaviors;
- Evidence created only from verified inbound artifacts or authoritative fake
  adapter observations;
- existing Web GET/polling may observe the resulting Case revision but receives
  no new channel control, identity, credential, or raw artifact.

No secret is required. Authenticity tests use conspicuously non-secret fixture
material and never claim to reproduce a real provider's cryptography.

### Phase 06B2 — real controlled test integration

This phase requires another proposal and explicit user approval. It must freeze:

- the real provider and capability, initially draft-only or an owned controlled
  test mailbox;
- account ownership and permitted recipients/senders;
- provider-specific authentication, webhook verification, event-ID semantics,
  idempotency support, reconciliation, rate limits, and failure mapping;
- secret storage and rotation;
- exact PII fields, encryption, retention, deletion, export, and incident
  handling;
- provider-specific Evidence sufficiency and whether any delivery state affects
  completion;
- deployment topology and callback reachability;
- real-provider terms and compliance review.

Gmail, email send, SMS, LiveKit, SIP, voice, and any other external system stay
inactive until this separate gate.

## Minimal interface changes for Phase 06B1

These are proposed shapes, not implemented contracts. Exact names may change in
the executable phase contract, but their authority must not.

### 1. Channel ingress seam

Add a channel-only control-plane route, separate from the Web Case event route:

```text
POST /channels/local_mailbox/events
raw request bytes + allowlisted authenticity headers
  -> verify authenticity and freshness
  -> resolve a server-owned ChannelBinding
  -> reserve/deduplicate InboxReceipt in PostgreSQL
  -> dispatch the stored Case command identity through Temporal
  -> return the prior or current bounded receipt
```

The payload may carry opaque external identifiers, but never an authoritative
`case_id`. Unknown or ambiguous bindings fail closed before a Case mutation.
The verifier receives raw bytes; parsed content is not trusted until verification
passes.

### 2. Deep channel module

Place the seam in `runtime/packages/connectors`, with a small transport-facing
interface:

```text
verify(raw_bytes, headers, received_at) -> VerifiedInbound | RejectedInbound
send(DeliveryAttempt) -> DeliveryObservation
lookup(DeliveryAttempt) -> DeliveryObservation | Unknown
```

The adapter does not receive a Runtime repository, mutate a Case, approve an
action, create canonical Evidence, or decide completion. The channel module
hides provider/local transport details, signature/header rules, and error
mapping. The caller and tests use the same interface.

### 3. PostgreSQL channel authority

Add private, versioned channel records rather than placing channel truth in
Temporal history or browser storage:

- `ChannelBinding`: server-owned mapping from opaque channel/account/thread
  references to exactly one Case and allowed direction;
- `InboxReceipt`: channel kind, external event ID, payload hash, binding ID,
  Case ID, stored command ID, first-seen time, authenticity/replay outcome, and
  processing state;
- `OutboxRecord`: delivery ID, Case/action/pin binding, exact rendered-payload
  hash, destination binding, stable idempotency key, lifecycle state, attempt
  metadata, and last redacted failure category;
- `DeliveryReceipt`: delivery ID, provider/local message ID when available,
  observation kind, observed time, artifact hash, and Evidence ID when accepted.

The Case CAS transition that authorizes a send and the first `OutboxRecord`
insert must commit atomically in one PostgreSQL transaction. The existing
`CaseRepository.replace()` interface cannot express this; 06B1 needs one
bounded atomic channel-mutation method or a deeper PostgreSQL unit-of-work
interface. Do not emulate atomicity with two independent writes.

### 4. Case command and event projection

Add distinct internal commands for verified inbound ingestion and channel
delivery observation. Do not widen the existing Web `consumer_message` body to
accept actor, channel, Case, or authenticity fields.

A verified inbound artifact projects to:

- one redacted/allowlisted `VisibleCaseEvent` with actor `provider` and a new
  explicit channel event type;
- one `EvidenceType.PROVIDER_MESSAGE` reference containing only the opaque
  source reference, content hash, timestamps, and media type;
- one monotonic Case revision/event cursor transition.

An outbound acknowledgement or delivery callback projects to
`EvidenceType.PROVIDER_EVENT` only after it matches the authoritative outbox
record. The existing Web receipt continues to require its current completion
Evidence and must not treat channel Evidence as sufficient.

### 5. Capability and authorization seam

The current `CapabilityManifest`, `CapabilityReference`, simulator adapter, and
executor are intentionally simulator-only. Do not disguise a channel send as a
simulator capability and do not generalize the synchronous simulator
`prepare/commit` protocol into a real-effect contract.

The 06B1 contract must choose and test one explicit evolution:

- allow a `channel` capability namespace and a bounded
  `channel.local_mailbox.send_message` capability in the canonical manifest;
- keep channel dispatch behind a separate durable dispatcher after reusing the
  same current-state, Delegated Authority, disclosure, approval, expiry, and
  pin checks.

For the recommended 06B1 scenario, only non-consequential `send_message` is
allowed under the Case's existing Delegated Authority and an allowlisted fixed
template/validated Fast response. `accept_offer`, disclosure beyond the
allowlist, changed material terms, or any other consequential action continues
to require the existing exact approval. A channel callback never grants
approval.

## Frozen authority, state, idempotency, and replay rules

### Authority

1. PostgreSQL owns Channel bindings, inbox/outbox state, delivery receipts,
   channel Evidence, and their relation to Case revisions.
2. Temporal owns only dispatch order, retry schedules, waits, timeouts, and
   reconciliation control state. A workflow history event is not a delivery
   receipt.
3. The ingress verifier owns authenticity and freshness classification. The
   adapter cannot select a Case.
4. A server-owned `ChannelBinding` owns Case correlation. Sender-supplied Case
   identifiers are never trusted.
5. Deterministic policy owns disclosure and send authorization. Model text and
   adapter success cannot bypass it.
6. Provider/local observations support Evidence only after matching the
   authoritative inbox/outbox binding. They do not by themselves authorize
   completion.

### Inbound idempotency and replay

1. Verify authenticity over the exact raw bytes before parsing or Case lookup.
2. Use `(channel_kind, external_event_id)` as the provider-event identity and
   store the raw-byte payload hash.
3. First valid receipt reserves one server-owned command UUIDv4 in PostgreSQL
   before Temporal dispatch.
4. Same external event ID plus same payload hash returns/reuses the prior inbox
   and command result; it appends no second Case event or Evidence.
5. Same external event ID plus a different payload hash fails closed as a
   replay/mismatch, produces no Case mutation, and records only allowlisted
   security metadata.
6. An unknown event outside the allowed freshness window fails closed. A known
   exact duplicate may resolve to its prior receipt after authenticity is
   rechecked.
7. Duplicate concurrent callbacks have one database winner. Temporal Update
   IDs and Case command receipts remain a second line of defense, not the
   global inbox authority.

### Outbound idempotency and reconciliation

1. Authorization and the first outbox insert are one PostgreSQL transaction.
2. The outbox owns a server-generated UUIDv4 delivery ID and stable idempotency
   key before the first adapter call. All retries reuse the exact rendered body,
   destination binding, and key.
3. A changed body, destination, Case/action/pin binding, or capability creates a
   new delivery intent and key; reuse with changed semantics fails closed.
4. `accepted` means only that the adapter/provider accepted the request.
   `delivered`, `bounced`, `failed_retryable`, and `failed_terminal` remain
   distinct authoritative observations.
5. A timeout or lost response triggers lookup/reconciliation before another
   send when the adapter supports lookup. If outcome remains unknown, the UI
   and audit state say unknown; they do not claim failure or delivery.
6. Provider/local message IDs are recorded when available and must match the
   delivery binding on later callbacks.
7. Phase 06B1 may prove one durable fake effect under fault injection. It makes
   no production exactly-once claim. Phase 06B2 must document the selected
   provider's real idempotency and duplicate-delivery limits.

### PII, redaction, and retention

1. Phase 06B1 accepts synthetic identities and synthetic message content only.
2. Raw bytes exist only long enough for verification, parsing, and hashing.
   Store the minimum redacted/allowlisted content needed for the Case event,
   plus immutable hashes and opaque references.
3. Do not store addresses, bodies, signatures, authorization headers, provider
   exception text, or raw callback payloads in operation logs, Temporal memo/
   search attributes, browser storage, or model traces.
4. Channel records and Evidence are excluded from training/data export by
   default. A later explicit consent and retention policy is required before
   any real feedback can enter a review quarantine.
5. Phase 06B2 must freeze retention and deletion durations before using real
   accounts or personal identifiers.

## Phase 06B1 acceptance criteria

1. Existing conversation UI, four-fact intake, Phase 06A recovery, exact
   approval, polling, final authoritative GET, and Evidence receipt tests remain
   unchanged and pass.
2. No Web request or persisted browser envelope gains channel identity,
   authenticity material, raw message content, or credentials.
3. A valid synthetic inbound event resolves only through a server-owned binding
   and creates exactly one Case event, one inbox receipt, and one matching
   Provider-message Evidence reference.
4. Unknown binding, ambiguous binding, invalid authenticity, stale unknown
   event, malformed body, actor mismatch, and Case-terminal paths fail closed
   before unauthorized mutation.
5. Same-event/same-body sequential and concurrent duplicates reuse one receipt;
   same-event/different-body replay returns a stable conflict/security category
   and mutates no Case.
6. A channel-triggered outbound message is authorized from current Case pins,
   Delegated Authority, disclosure policy, and current capability before one
   atomic Case-plus-outbox commit.
7. Worker crash before adapter call, lost response after adapter acceptance,
   retry exhaustion, worker replacement, and API restart preserve one stable
   delivery identity and reconcile without inventing delivery.
8. Duplicate, delayed, reordered, mismatched, and unknown delivery callbacks
   cannot create duplicate or cross-Case Evidence or regress outbox state.
9. Acceptance, delivery, bounce, retryable failure, terminal failure, and
   unknown outcome remain distinguishable in PostgreSQL and in allowlisted
   operation evidence.
10. Channel Evidence does not satisfy the existing completion predicate unless
    a separately frozen deterministic verifier rule explicitly requires and
    validates it. For 06B1, existing fictional-Provider completion semantics
    remain unchanged.
11. Operation logs and error responses contain only allowlisted IDs, states,
    timings, and failure categories; adversarial bodies, addresses, headers,
    signatures, and exception text do not appear.
12. Temporal history carries compact IDs and state only; raw message content,
    signatures, and channel credentials are absent.
13. Disposable PostgreSQL plus Temporal tests prove inbox reservation, atomic
    outbox creation, retries, callback dedupe, restart recovery, and CAS races.
14. Focused contract, Case Runtime, API, worker, connector, and Web suites pass;
    one stable-diff `make preflight` passes after implementation.
15. Fresh independent review has no unresolved Blocking, Important, or Minor
    finding before integration.
16. No external network call, real account, credential, deployment, release,
    production capacity, or production exactly-once claim is part of the 06B1
    evidence.
17. Integration returns `harness/status.toml` to idle and leaves 06B2 and voice
    unauthorized.

## Non-goals

- changing the conversation UI, intake flow, Case recovery, approval,
  polling, finalizing, completion, or receipt behavior;
- replacing the fictional Provider simulator with an email Provider;
- Gmail, Outlook, SMS, Slack, WhatsApp, MCP, real webhooks, or any other real
  service in 06B1;
- LiveKit, SIP, phone calls, ASR, TTS, recordings, interruption, or voice
  latency work;
- credentials, OAuth, secret manager, production authentication,
  multi-tenancy, account linking, deployment, public callback URLs, or release;
- arbitrary attachments, HTML rendering, links, file downloads, or unbounded
  message history;
- browser-side channel sends or credentials;
- channel-driven changes to existing material terms or approval pins;
- treating provider acceptance as delivery or treating delivery as Case
  completion;
- claiming production exactly-once, throughput, latency, capacity,
  availability, compliance, or production readiness;
- automatic training ingestion from channel traffic;
- Phase 06B2, Phase 07, or any model training/serving expansion.

## Risks, dependencies, and open decisions

### Risks

- **Atomicity seam**: extending the repository incorrectly could persist a Case
  authorization without an outbox record or vice versa.
- **Contract contamination**: broadening simulator contracts mechanically could
  let channel operations bypass channel-specific durability and security rules.
- **False Evidence**: adapter acknowledgements or callbacks can be forged,
  replayed, reordered, or mis-correlated unless matched to authoritative state.
- **PII expansion**: real channel content changes the data classification of
  Case state, logs, traces, backups, and test fixtures.
- **UI truthfulness**: channel states must not be mapped onto the existing
  completion receipt without a new approved product requirement.
- **Provider coupling**: provider-specific verification or reconciliation in
  the core module would make the seam shallow and hard to replace.

### Dependencies for an executable 06B1 contract

- approve Option A and the `local_mailbox` first-channel choice;
- approve bounded PostgreSQL channel schema and one atomic channel-mutation
  interface;
- approve the canonical capability namespace evolution described above;
- freeze the one synthetic inbound/outbound scenario and exact fake adapter
  state machine;
- freeze retention as synthetic-only/minimum-storage for 06B1;
- keep existing Web HTTP contracts and UI behavior as compatibility gates.

### Decisions deliberately deferred to Phase 06B2

- real provider selection and account ownership;
- credential, OAuth, secret storage, and rotation;
- provider-specific webhook signature and replay rules;
- public callback/deployment topology;
- real address/body/header storage, encryption, retention, deletion, and user
  export;
- real-provider idempotency, reconciliation, rate limits, and delivery SLA;
- whether a real channel artifact may ever satisfy a completion verifier;
- voice/recording/disclosure requirements.

## Gate conclusion

`GO_FOR_PHASE_PROPOSAL`

The current code provides reusable Case authority, approval pins, optimistic
concurrency, command receipts, Temporal ordering/recovery, Evidence contracts,
and a stable Web recovery surface. It does not provide a channel adapter,
webhook authenticity, global replay ledger, durable outbox, delivery receipt,
or real-effect executor. The recommended 06B1 proposal is therefore feasible
only as a new, separately approved local/fake controlled-mailbox phase.

The user approved Option A, the 06B1/06B2 split, the bounded PostgreSQL channel
interface, and creation of an executable Phase 06B1 contract on 2026-08-26.
Root Sol deliberately narrowed 06B1 to a deterministic, non-model-advertised
local reply, so canonical Capability Manifest evolution remains deferred.
Phase 06B2 and every real Provider/MCP/email/voice path remain inactive.
