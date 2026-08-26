# Phase 06B1 — Local Controlled Mailbox

**Status**: Complete locally and independently approved on 2026-08-26 from
integrated `main` at `40e324f`. Hosted integration is pending. This phase implements one synthetic,
credential-free local mailbox over the existing scripted/PostgreSQL/Temporal
Case. It does not authorize Phase 06B2 or any real Provider, email, MCP, voice,
credential, deployment, or release.

## Go decision

**GO** for the bounded local/fake slice. Phase 05A supplies durable command
ordering, retries, worker recovery, and PostgreSQL command receipts. Phase 06A
supplies authoritative Case recovery and truthful UI polling. Phase 06B1 may
add the missing channel seam, server-owned binding, inbox/outbox authority,
delivery observations, and fault evidence without changing the current Web
flow or contacting an external system.

## Objective

Implement one bidirectional, email-shaped `local_mailbox` that can ingest a
synthetic fictional-Provider message, append one authoritative Case event and
Provider-message Evidence, authorize one bounded non-consequential reply,
atomically persist its outbox record with the Case transition, dispatch it
through a deterministic local adapter under Temporal, and ingest an
authoritative synthetic delivery callback. Duplicate, replayed, reordered,
lost-response, retry, API restart, and worker restart paths must not duplicate
Case events, outbox records, delivery receipts, or Evidence.

## Preserved product and authority boundaries

- Preserve the conversation UI, four-fact intake, Task Brief, Offer, exact
  Approval, Phase 06A Case recovery, bounded polling, final authoritative GET,
  completion, and Evidence receipt behavior. No Web source or test needs a new
  channel control or storage field.
- Keep `apps/web/lib/runtime-client.ts` as the only Web-to-Runtime seam. The
  existing create/event/approval bodies and response semantics remain
  compatible.
- PostgreSQL owns Case state, channel binding, inbox receipt, outbox record,
  delivery receipt, channel Evidence, and their revisions. Temporal owns only
  ordering, retry, waits, recovery, and compact references.
- External bytes are untrusted. Authenticity/freshness classification occurs
  before Case correlation or mutation; only a server-owned binding selects a
  Case.
- Models do not verify, correlate, authorize, dispatch, create Evidence, or
  complete a Case. Temporal mode remains scripted and credential-free.
- Channel Evidence is stored in the authoritative Case snapshot, but the
  existing top-level Runtime `evidence` projection remains limited to the
  current simulator-transition/confirmation receipt evidence. Channel delivery
  cannot satisfy the existing completion predicate in this phase.

## Frozen scope choices

### No canonical capability expansion

Phase 06B1 does not widen the canonical model-visible `CapabilityManifest`,
`CapabilityReference`, generated schemas, or model action vocabulary. The one
local reply is a deterministic channel response to a verified inbound event,
not a model-proposed capability. A channel dispatcher must revalidate:

- current Case/strategy/planning pins;
- `ActionType.SEND_MESSAGE` in the current Delegated Authority `allowed_actions`;
- no pending execution, terminal Case, or stale revision;
- an exact allowlisted response equal to the accepted scripted Fast response;
- synthetic destination binding and local-only adapter mode.

Any model-visible channel capability, arbitrary message, changed disclosure,
real provider adapter, or MCP surface requires the Phase 06B2 gate.

### Channel package and seam

Promote `runtime/packages/connectors` from a placeholder to the inward
`proxyloop_connectors` package. It owns only transport-neutral channel records,
the local raw-byte verifier, the delivery adapter interface, and the
deterministic local adapter. It does not import API, workflow worker,
Case Runtime, simulator, model, or Web packages.

Its narrow external adapter interface is:

```text
verify(raw_bytes, headers, received_at) -> VerifiedLocalMailboxEvent
send(DeliveryAttempt) -> DeliveryObservation
lookup(DeliveryAttempt) -> DeliveryObservation | Unknown
```

The strict attempt is required for restart-safe local reconciliation. An
adapter lookup may return only a previously observed acceptance; an unseen
attempt remains `Unknown`. A replacement worker first reuses PostgreSQL's
stored accepted truth, otherwise it retries the same immutable, idempotent
attempt and receives the same synthetic provider-message identity.

The Case Runtime owns correlation, authorization, Case projection, Evidence,
and persistence coordination. The workflow worker owns Temporal dispatch. The
API owns HTTP/header adaptation and redacted status mapping.

## Frozen local ingress contract

Add one API-local route not used by the Web:

```text
POST /channels/local_mailbox/events
```

Headers:

- `X-ProxyLoop-Local-Timestamp`: canonical UTC timestamp;
- `X-ProxyLoop-Local-Signature`: `sha256=<lowercase SHA-256 of the exact raw
  request bytes>`.

This signature is conspicuously non-secret fixture authenticity. It proves
raw-byte binding and failure semantics only; it is not cryptographic provider
authentication and creates no 06B2 claim.

Strict request body:

```json
{
  "schema_version": "local-mailbox-v1",
  "event_id": "lowercase UUIDv4",
  "binding_ref": "fictional-provider-local-mailbox",
  "occurred_at": "UTC timestamp",
  "kind": "provider_message | delivery",
  "content": "provider_message only, 1..4000 characters",
  "delivery_id": "delivery only, lowercase UUIDv4",
  "provider_message_id": "delivery only, non-empty opaque reference",
  "delivery_status": "delivered | bounced"
}
```

Command-specific validation forbids irrelevant fields and unknown keys. The
body cannot carry `case_id`, actor, approval, authorization, credentials,
headers, or arbitrary channel/provider configuration.

Bounded success response:

```text
schema_version, event_id, command_id, case_id, revision, event_cursor,
deduplicated, delivery_id, delivery_status
```

Stable redacted failure categories include invalid fixture authenticity,
unknown/stale event, unknown binding, replay mismatch, channel conflict, and
channel dependency unavailable. Error responses and operation records never
include raw bodies, message content, binding internals, signature/header values,
provider exception text, or credentials.

## Frozen identity and correlation

- Channel kind is exactly `local_mailbox`.
- Binding ref is exactly `fictional-provider-local-mailbox` in this slice.
- PostgreSQL creates the server-owned binding for the existing scripted Case as
  part of successful Case creation. No public binding-management route exists.
- The binding maps one synthetic Provider mailbox/thread to one Case and
  permits inbound Provider messages plus outbound replies.
- Request `binding_ref` is only a lookup key; the PostgreSQL binding owns the
  Case ID. Unknown or mismatched binding fails before Case mutation.
- Delivery callbacks additionally bind to the authoritative `delivery_id`,
  stored provider-message ID, outbox Case, and binding. No callback field may
  redirect the receipt to another Case.

## Frozen PostgreSQL channel state

Add private versioned channel tables through the repository's existing bounded
local bootstrap approach. Do not introduce a general migration framework in
this phase.

### `ChannelBinding`

- channel kind, binding ref, Case ID, synthetic local/remote refs, allowed
  directions, active state, created time;
- binding ref is unique and maps to exactly one Case.

### `InboxReceipt`

- `(channel_kind, event_id)` unique provider-event identity;
- exact raw-byte payload hash, binding ref, Case ID, server-owned UUIDv4
  command ID, first-seen time, event kind, and processing state;
- the stored command ID is reserved before Temporal dispatch and reused for
  every exact retry.

### `OutboxRecord`

- UUIDv4 delivery ID and idempotency key;
- Case ID, binding ref, source inbox/command ID, source Case/strategy/event pins,
  exact synthetic rendered body and body hash;
- lifecycle state `pending | accepted | delivered | bounced |
  failed_retryable | failed_terminal | unknown`;
- provider-message ID when known, attempt count, timestamps, and one allowlisted
  failure category.

### `DeliveryReceipt`

- delivery ID, provider-message ID, observation state, artifact hash,
  observed/captured times, and canonical Evidence ID;
- observations are append-only and order-validated. Duplicate exact
  observations reuse the prior receipt; mismatched or regressive observations
  fail closed.

The Case CAS update that records a verified inbound event and authorizes the
reply must insert the first OutboxRecord in the same PostgreSQL transaction.
Expose one bounded atomic repository interface for that operation. Do not
emulate atomicity with a Case write followed by an independent outbox write.

The existing `CaseRepository.create/get/replace` interface and in-memory/direct
behavior remain compatible. Channel methods are an additional PostgreSQL-only
interface used only by explicit Temporal/local-mailbox mode.

## Frozen internal command and Temporal rules

Extend the backward-compatible internal Case command family with:

- `ingest_channel_event`: verified provider content, binding/event references,
  content hash, expected Case revision, and occurred time;
- `record_channel_delivery`: delivery/provider-message references, delivered or
  bounced observation, artifact hash, expected revision, and occurred time.

Old Phase 05A commands and captured workflow histories must remain decodable and
replayable. New channel-only fields are forbidden on old command types. Channel
commands use a Phase 06B1 internal schema discriminator while preserving old
Phase 05A values.

For a provider message:

1. API verifies exact raw bytes and timestamp.
2. PostgreSQL resolves the binding and reserves/deduplicates InboxReceipt plus
   one command UUIDv4.
3. API dispatches that command to the existing CaseWorkflow by Update.
4. Case activity revalidates the inbox/binding and applies one provider-visible
   event plus one `EvidenceType.PROVIDER_MESSAGE`.
5. Scripted Fast produces the fixed bounded response. Deterministic channel
   authorization validates `SEND_MESSAGE` and current pins.
6. One atomic PostgreSQL transaction CAS-updates the Case, marks the inbox
   applied, and inserts the pending outbox.
7. Workflow schedules a separate delivery activity with only compact Case,
   delivery, and idempotency references.
8. The local adapter returns a deterministic `accepted` observation and stable
   synthetic provider-message ID. A same-process lost response is recovered by
   lookup. A replacement worker reuses persisted accepted truth or, while the
   outcome remains unknown, retries the same idempotent delivery identity.
9. PostgreSQL records accepted state without claiming delivery or completion.

For a delivery callback, the same ingress verification/reservation rules apply.
The Case command validates the outbox/provider-message binding, atomically
records delivered or bounced state, appends one Provider-event Evidence, marks
the inbox applied, and advances the Case revision without changing existing
approval, Provider execution, or completion truth.

Temporal carries only command/transition/delivery references. Raw request bytes,
message bodies, signatures, headers, binding records, credentials, and full
Case snapshots are absent from Workflow carry state, memo, and search
attributes.

## Frozen idempotency and replay rules

### Inbound

1. Recheck fixture authenticity over exact raw bytes on every request.
2. Same event ID plus same payload hash reuses the stored inbox command and
   result; it creates no second event, outbox, delivery receipt, revision, or
   Evidence.
3. Same event ID plus different payload hash is `channel_replay_mismatch`, with
   no Case mutation or second command.
4. Concurrent identical callbacks have one PostgreSQL reservation winner.
5. Unknown events outside a five-minute fixture freshness window fail closed.
   A known exact duplicate may resolve to its prior receipt after authenticity
   is rechecked.
6. PostgreSQL inbox uniqueness is global channel authority; Temporal Update ID
   and Case command receipt deduplication are additional defenses.

### Outbound

1. Delivery ID, exact body, destination binding, source pins, and idempotency
   key are stored before the first adapter call.
2. Every retry uses the exact stored attempt. Changed semantics require a new
   authorized outbox record and cannot reuse a key.
3. On timeout/lost response, the activity calls `lookup` before a second send.
4. `accepted` is not `delivered`; unknown outcome stays unknown. A later
   callback is the only Phase 06B1 path to delivered/bounced.
5. The deterministic adapter may prove singular fake acceptance under retries;
   this phase makes no real-effect or production exactly-once claim.

## PII, retention, and observability

- Accept synthetic identities and content only. The one binding and scenario
  are repository fixtures, not user or provider data.
- Raw inbound bytes exist only for verification, strict parsing, hashing, and
  the current request. Persist only the allowlisted synthetic content needed
  for the Case event, exact outbound retry, hashes, and opaque references.
- Existing browser storage remains unchanged and receives no channel material.
- Operation logs add only allowlisted channel kind, event kind, outcome,
  delivery state, Case ID when safely known, revision, status, and latency.
- Never log or persist request headers/signatures, arbitrary exception bodies,
  or credentials.
- Channel artifacts are excluded from training/data export. Real PII retention,
  encryption, deletion, consent, and quarantine remain Phase 06B2 decisions.

## Frozen fault matrix

| Fault | Required proof |
|---|---|
| Invalid signature or stale unknown event | Stable redacted rejection; no inbox/Case/outbox mutation |
| Unknown binding | No Case correlation or mutation |
| Same event/same body, sequential or concurrent | One inbox command, Case event, outbox, revision sequence, and Evidence |
| Same event/different body | Replay mismatch; prior result unchanged |
| API loses response after inbox reservation | Exact retry reuses command and reaches one outcome |
| Worker stops before Case activity | Replacement worker applies reserved command |
| PostgreSQL failure before atomic Case/outbox commit | Neither Case transition nor outbox is committed |
| Activity loses response after local acceptance | Known lookup, persisted truth, or an exact idempotent retry returns the same provider-message ID; no duplicate outbox or logical acceptance |
| API/worker restart after accepted state | PostgreSQL preserves pending delivery identity and accepted truth |
| Duplicate/reordered delivery callback | One monotonic receipt/Evidence; no state regression |
| Mismatched delivery/provider-message/Case binding | Conflict; no Evidence or outbox change |
| Delivered or bounced callback | Truthful distinct terminal delivery state; existing Case completion unchanged |
| Phase 05A captured history replay | No nondeterminism or schema-decode failure |
| Existing Web flow | All Phase 06A behavior/tests pass unchanged |

## Acceptance criteria

1. The frozen ingress, identity, repository, command, Temporal, idempotency,
   replay, PII, observability, and fault rules are implemented without real
   network calls or credentials.
2. Existing Web source and browser envelope remain unchanged; the focused 47
   Web tests, lint, typecheck, and build pass.
3. Existing direct memory/PostgreSQL and Phase 05A commands, receipts, API
   routes, workflow replay, approval expiry, worker recovery, and completion
   behavior remain compatible.
4. `proxyloop_connectors` exposes a small verifier/send/lookup interface and a
   deterministic local adapter; it has at least a fault-injection test adapter
   and no dependency on API, workflow, Case Runtime, simulator, model, or Web.
5. Valid inbound creates exactly one server-correlated Provider event, matching
   Provider-message Evidence, InboxReceipt, authorized OutboxRecord, and stable
   delivery identity.
6. Invalid/stale/unknown/malformed/mismatched/replayed input fails closed with
   no unauthorized mutation and no raw data in logs or errors.
7. Case update plus first outbox insert is one PostgreSQL transaction; fault
   injection proves no split commit.
8. Temporal dispatch, activity retry, lost response, lookup, worker replacement,
   and process restart preserve exact delivery identity and accepted/unknown
   truth.
9. Delivery callbacks are correlated to the stored outbox/provider-message
   pair and produce one monotonic delivered or bounced receipt plus one
   Provider-event Evidence.
10. Top-level Runtime receipt Evidence and completion predicate remain unchanged;
    channel Evidence cannot complete the existing Case.
11. Focused connector, Case Runtime, API, operation-redaction, Temporal replay,
    real disposable PostgreSQL/Temporal fault, and prior regression tests pass.
12. Runtime Ruff, strict mypy, both uv locks, contract/artifact drift, layout,
    diff, Compose, Web checks, and one stable-diff `make preflight` pass.
13. Browser smoke confirms the existing approval-through-Evidence flow at 1280
    px and 375 px with no new console warning/error or horizontal overflow.
14. Fresh independent Terra review has no unresolved Blocking, Important, or
    Minor finding; Sol reads the complete diff and owns every final claim.
15. Hosted phase-gate and GitGuardian pass before squash merge. Integration
    returns Harness status to idle and leaves 06B2, real Provider/MCP/email,
    credentials, voice, deployment, and release unauthorized.

## Explicitly out of scope

- Gmail, Outlook, email sending, MCP, SMS, Slack, WhatsApp, real webhook,
  Provider account, OAuth, credential, or external network call;
- LiveKit, SIP, phone number, ASR/TTS, recording, interruption, voice latency,
  audio persistence, or disclosure flow;
- model call, model-visible channel capability, arbitrary action/message,
  new disclosure, changed material terms, or channel-owned approval/completion;
- conversation UI, intake, browser persistence, polling, routing, visual design,
  second Case/journey/vertical, attachment, HTML, link, or file handling;
- authentication, account linking, multi-tenancy, general migration framework,
  deployment, public callback, release, or production operations;
- production exactly-once, throughput, latency, capacity, availability,
  compliance, or production-readiness claims;
- training/data ingestion from channel traffic;
- Phase 06B2 or Phase 07.

## Ownership and verification

- Root Sol owns this contract/status, repository and channel interfaces,
  authority/idempotency/replay/completion/security semantics, scope decisions,
  complete-diff review, final verification truth, Git integration, and gate
  closure.
- One Luna xhigh implementer may own the bounded product/test/doc slice after
  this contract is frozen. It may not edit this contract, Harness status,
  independent review, or execution log; commit, push, merge; use a real
  provider/credential; or expand scope.
- One fresh Terra high reviewer performs read-only defect-first review after the
  diff is stable. Accepted findings return to the same implementer unless Sol
  owns a small shared-interface correction.
- Run focused checks while behavior changes, then real disposable
  PostgreSQL/Temporal faults, Browser smoke, one final `make preflight`, one
  concise execution log, hosted CI/GitGuardian, squash merge, safe branch
  cleanup, and stop before Phase 06B2.

## Stop conditions

Stop and request a new user decision if implementation requires a real provider,
MCP, credential, external network, model-visible channel capability, Web flow
change, real PII, destructive migration, deployment/release, production claim,
voice, Phase 06B2, or work beyond this one synthetic local mailbox. Otherwise
continue through bounded integration and return to idle.
