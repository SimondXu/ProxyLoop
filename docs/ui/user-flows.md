# Local conversation flow

```text
blank conversation
  -> user describes lower-bill outcome
  -> Runtime-created Case snapshot
  -> inline Task Brief and proactive constraint question
  -> user confirms hotspot + device financing constraint
  -> one consumer event to the Runtime
  -> Runtime Progress / Offer / pending Approval
  -> exact approval pins returned by Runtime
  -> verifier-backed Evidence receipt or blocked state
```

The first natural-language message establishes the conversation intent in the
UI. The only consumer event sent by this demo is the explicit constraint
confirmation. The event and approval calls are made through
`lib/runtime-client.ts`; no client-generated revision or completion identifier
is accepted as authority.

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
If a pending approval receives an arbitrary correction, the UI records it only
as a local note and says that changing the created Case is unsupported in this
demo.

Every create, confirmation-event, and approval request is bound to the current
conversation session. Restarting clears the session and invalidates late
responses, so an old Case, approval, or receipt cannot reappear in the new
conversation.
