# Phase 07A Reproducible Local Portfolio Demo Independent Review

**Date**: 2026-08-26
**Reviewer**: independent read-only Terra reviewer
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- isolated Compose and host-process lifecycle, reset scope, PID ownership,
  readiness, normal stop, restart, and concurrent lifecycle commands;
- deterministic Web Case, synthetic `local_mailbox`, PostgreSQL/Temporal
  authority, duplicate/recovery, Evidence, and browser-channel isolation;
- Make targets, focused tests, portfolio claims, phase boundaries, and the
  complete material Phase 07A diff.

The reviewer was read-only and made no real Provider, email, MCP, voice,
credential, deployment, release, or file-system change.

## Findings and remediation

| Severity | Finding | Resolution |
| --- | --- | --- |
| Important | Two concurrent starts could pass the PID-file check before host spawn, overwrite lifecycle state, or stop another instance's Compose dependencies. | The supervisor now atomically claims `lifecycle.lock` before ports, Compose, Web build, or host spawn and holds it through cleanup. |
| Important follow-up | A stop/reset or second start could interleave before lifecycle-lock acquisition and erase an active stop sentinel. | A short `fcntl` command mutex now serializes start/stop/reset state transitions. Start claims lifecycle ownership before clearing stale state; stop/reset hold the mutex through supervisor release and bounded cleanup; a concurrent start fails closed. |
| Important closeout | The frozen contract required a bounded Harness log and removal of root planning scratch before merge. | Phase 07A now has one execution log under `harness/log/`; `task_plan.md`, `findings.md`, and `progress.md` were removed before the final diff. |
| Minor | README/PLANS initially described the phase as complete while review and final verification were still active. | The interim wording was narrowed during review and changed to complete only after final approval and idle closeout. |

Root also replaced `next dev` with a production Web build/start path after a
live run showed that the development server rewrote tracked `next-env.d.ts`.
The final startup no longer dirties that file.

## Final rereview

The final Terra rereview returned **Approve** with no unresolved Blocking,
Important, or Minor finding. It confirmed that the atomic lifecycle lock and
shared command mutex resolve the two-start and startup-vs-stop/reset races
without introducing a cleanup deadlock. Focused regressions cover second-start
refusal, claim-before-clear ordering, active-stop preservation, and stop during
startup.

Root Sol independently reviewed the complete script, tests, Make targets,
documentation, Runtime channel projection, live lifecycle evidence, and phase
boundaries and owns the final verification and integration claims.

## Scope conclusion

Approval applies only to the credential-free local portfolio demo and its two
truthful scenes. It does not authorize Gmail, Voice, MCP, consumer auth, real
Provider contact, models, ML reruns/promotion, deployment, release, production
exactly-once, monitoring, capacity, or production-readiness claims.
