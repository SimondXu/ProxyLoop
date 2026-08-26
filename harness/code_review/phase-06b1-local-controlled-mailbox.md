# Phase 06B1 Local Controlled Mailbox Independent Review

**Date**: 2026-08-26
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- strict raw-byte fixture verification, freshness, binding, inbox reservation,
  replay classification, and redacted API errors;
- PostgreSQL Case-plus-outbox atomicity, delivery observation monotonicity,
  receipt deduplication, and authoritative Case projection;
- Temporal channel command compatibility, delivery activity retry, lost
  response, worker replacement, and replay;
- unchanged Web response behavior, channel-material filtering, Make/CI gates,
  architecture documentation, and the complete Phase 06B1 diff.

The reviewer was read-only and made no real Provider, email, MCP, voice, or
network-channel call and no file edit, commit, push, deployment, or release.

## Findings and remediation

The initial and intermediate reviews returned **Request Changes**. Root froze
the remediation semantics and the bounded implementer changed only the owned
connector, worker, API, and regression-test slices.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Blocking | The existing Case response serialized the full authoritative snapshot, exposing local-mailbox event content and channel Evidence to the unchanged browser client. | The API now projects from a serialized copy, removes only Phase 06B1 channel events/Evidence, and preserves revision, event cursor, pins, completion, top-level receipt Evidence, and the pre-06 provider-offer Evidence. |
| Important | The process-local adapter could not reconcile a lost acceptance after worker replacement. | Delivery lookup now consumes the complete immutable `DeliveryAttempt`; persisted accepted or terminal outbox truth short-circuits adapter calls, and an unresolved replacement uses the same deterministic idempotent attempt and provider-message identity. |
| Blocking follow-up | A fresh adapter synthesized `accepted` for any unseen attempt, so `fail_before_accept` could become accepted without a successful send. | An unseen lookup is now `Unknown`; only a known adapter observation or persisted outbox state is accepted. Unknown retries perform one exact idempotent resend. Tests distinguish fail-before-accept, same-process lost response, persisted acceptance, and the process gap. |
| Important follow-up | An unrecognized stored outbox state could enter lookup/send before PostgreSQL rejected its transition. | The activity now allowlists only `pending`, `failed_retryable`, and `unknown` before dispatch. All other unrecognized states fail closed with zero lookup, send, or observation write. |

Root also corrected reservation ordering so an unknown event is freshness-
checked before binding lookup while an exact previously known duplicate may
reuse its receipt after authenticity re-verification.

## Final rereview

The final Terra rereview returned **Approve** with no unresolved Blocking,
Important, or Minor finding. It confirmed the browser projection, accepted /
unknown truth, stored-state short circuit, corrupt-state fail-closed guard,
freshness ordering, PostgreSQL atomicity, Phase 05A compatibility, redaction,
and CI target shape.

Root Sol independently read the affected authority, repository, API, adapter,
activity, workflow, and test paths and owns the live-dependency, Browser, final
preflight, integration, and completion claims.

## Authority and scope conclusion

The approved slice is only the credential-free deterministic `local_mailbox`.
It preserves PostgreSQL as Case/channel truth and Temporal as ordering/retry
owner, while the existing Web receives no channel material. It makes no real-
effect, production exactly-once, Provider, email, MCP, credential, voice,
authentication, deployment, release, or production-readiness claim. Phase
06B2 remains unauthorized.
