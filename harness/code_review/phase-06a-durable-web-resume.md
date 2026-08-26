# Phase 06A Durable Web Case Resume Independent Review

**Date**: 2026-08-26
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- the existing conversation workspace, Runtime client, local envelope, and
  focused Web tests;
- refresh/reconnect and worker/API restart recovery through readiness and the
  authoritative PostgreSQL Case projection;
- pending command identity, exact-body retry, same-Case receipt fingerprinting,
  409 reconciliation, and monotonic revision/event-cursor handling;
- pending approval, expiry, pending execution, completion, and Evidence receipt
  presentation;
- error copy, bounded visibility-aware polling, docs, and the complete frozen
  Phase 06A diff.

The reviewer was read-only and made no Provider/model/channel call, external
effect, file edit, commit, push, or merge.

## Findings and remediation

The initial review returned **Request Changes**. One bounded remediation and a
test-fixture correction were independently rereviewed.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Important | The persisted envelope validated duplicated body/pin/Case fields independently, so a shaped envelope could dispatch a retry different from its stored exact body. | Cross-field validation now binds create facts, event revision, approval pins, pending Case ID, and workspace Case locator; adversarial envelopes are rejected. |
| Important | A failed finalizing GET was swallowed, leaving a static Finalizing state without reconnect. | Poll failure preserves the locator/key, displays a truthful recoverable error, and exposes reconnect; a failure-to-completion test covers it. |
| Minor | Known pending event/approval recovery replayed POST before reading PostgreSQL. | Recovery now checks readiness and GETs a known Case first, avoids an already-applied replay, and sends the exact stored command only when still unresolved. |
| Important follow-up | Normal approval tests used a wall-clock date that would soon expire; a far-future replacement overflowed the timer limit. | Normal fixtures now use a bounded module-time `Date.now() + 1h`; expiry tests retain explicit past time. The final suite has no timer-overflow warning. |

Root also required bounded deadline backoff, a fresh polling budget per semantic
command, pause/resume on `visibilitychange`, and truthful
`temporal_unavailable` copy for an unfinished orchestration attempt including
retry exhaustion. Each path has focused coverage.

## Final rereview

The final rereview returned **Approve** with no unresolved Blocking, Important,
or Minor finding. It passed the 47-test Web suite and `git diff --check`, and
confirmed that the earlier envelope, GET-first, poll-failure, visibility,
Temporal-copy, and time-fixture findings remained closed.

Root Sol independently read the affected contracts and product paths and owns
the real-dependency, Browser, final preflight, integration, and completion
claims.

## Authority and scope conclusion

The approved slice preserves PostgreSQL as Case/approval/Evidence/completion
truth and Temporal as orchestration owner. Browser storage remains only a
strict locator plus one exact uncertain retry. No new HTTP route, SSE,
WebSocket, visual redesign, second Case, real Provider/model/tool/channel,
credential, auth, deployment, release, production exactly-once, capacity, or
production-readiness claim is approved. Phase 06B remains unauthorized.
