# Local conversation flow

```text
blank conversation
  -> user describes lower-bill outcome
  -> local progressive intake: current bill, target bill, hotspot, financing
  -> local Draft Task Brief with missing/confirmed rows and Edit actions
  -> explicit Create fictional Case action
  -> Runtime-created Case root/snapshot verified against the draft
  -> inline Task Brief and proactive constraint question
  -> user confirms hotspot + device financing constraint
  -> one consumer event to the Runtime
  -> Runtime Progress / Offer / pending Approval
  -> exact approval pins returned by Runtime
  -> verifier-backed Evidence receipt after authoritative GET, or blocked state
```

On mount or reconnect, a versioned local locator first checks
`GET /health/ready` and then reads `GET /cases/{case_id}`. Network/503 preserves
the locator and exact pending command; 404 reports a bounded store mismatch. A
pending create, event, or approval keeps one lowercase UUIDv4
`Idempotency-Key` and exact request body across an uncertain retry.

The first natural-language message establishes the conversation intent in the
UI. Supported input starts a local progressive intake and does not create a
Case. USD amounts are parsed strictly, and false fixed constraints,
unsupported currencies, negative values, malformed values, and incompatible
fixed-offer amounts stay local with retry guidance. The only consumer event
sent by this demo is the explicit constraint confirmation. The event and approval calls are made through
`lib/runtime-client.ts`; no client-generated revision, Case identifier, or
completion identifier is accepted as authority. Every POST is followed by an
authoritative Case read before its effect is presented as stable.

The API request contains exactly `current_monthly_total`,
`target_monthly_total`, `mobile_hotspot_required: true`, and
`device_financing_change_forbidden: true`. The Web verifies the returned root
Case and `snapshot.case` contain the same Case identity, exact Money values,
required/forbidden sets, and `Do not change device financing.` hard constraint.
The same invariant is applied to later snapshot-bearing responses.

Before creating a Case, the blank conversation applies a small English lexical
gate: the request must independently mention a mobile, cell, or phone context,
a billing context such as bill, cost, price, plan, or monthly, and an explicit
reduction outcome such as lower, reduce, save, cheaper, decrease, or cut.
Unsupported first messages stay local, explain that this demo only lowers a
fictional mobile bill, and invite a clear retry. This is an interaction
boundary, not general language understanding, and it does not claim support
for arbitrary or Chinese input.

If the Runtime returns HTTP 409/503, network failure, non-JSON, or a malformed
payload, the conversation stays open with a retry/restart/refresh explanation.
If a created Case receives an arbitrary correction, the UI records it only as a
local note and says to restart the local Runtime, then choose `New task`.
Changing the created Case is unsupported in this demo because its fixture IDs
are fixed.

Every create, confirmation-event, and approval request is bound to the current
conversation session. Restarting clears the local presentation and locator but
does not claim to delete the PostgreSQL Case. Responses apply monotonically by
Case, revision, and event cursor, so an old Case, approval, or receipt cannot
regress the current conversation.
