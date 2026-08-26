# Phase 04D Control-Plane Operations Independent Review

**Date**: 2026-08-26
**Reviewer**: fresh independent read-only Terra reviewers
**Initial recommendation**: Request Changes
**Final recommendation**: Approve

## Scope reviewed

- one allowlisted, correlated, non-retaining JSON operation record per Case or
  health HTTP operation;
- request, path, exception, credential, database URL, prompt, payload, and
  header redaction;
- liveness and read-only configured-storage readiness with no Case mutation or
  model dispatch;
- storage, model, request-validation, stale-CAS, conflict, and internal error
  categorization;
- explicit memory/PostgreSQL and scripted/model selection without automatic
  fallback;
- the injected fake-model PostgreSQL to scripted PostgreSQL controlled switch;
- the credential-free local diagnostic profile, Make/CI wiring, compatibility,
  documentation truth, and the complete staged Phase 04D diff.

The reviews were read-only. They made no external model or Provider call, used
no credential, and did not edit, commit, push, or merge.

## Initial review and remediation

The first Terra review returned **Request Changes** with one Critical and three
Important findings.

| Severity | Finding | Resolution |
| --- | --- | --- |
| Critical | A matched route with an invalid UUID copied the raw path parameter into the operation record and labeled HTTP 422 as success. | Case IDs are now recorded only after UUID canonicalization; FastAPI's compatible 422 response is preserved and observed as `request_invalid`. |
| Important | An unhandled exception produced a redacted 500 after the middleware response path, so the correlation header was absent. | The observation middleware now owns the stable redacted internal-error response before adding the correlation header and emitting its record. |
| Important | A recorder exception could turn liveness into an uncorrelated 500 and lose the operation record. | Recorder failures are isolated from the response and fall back once to the same non-retaining allowlisted JSON sink without exception text. |
| Important | The PostgreSQL controlled-switch test used wrappers around scripted adapters while labeling the Runtime as model-backed. | The test now uses the actual `OpenAICompatibleAdapter` with an injected fake client, proves one Slow and one Fast parse with no network, then explicitly reconstructs a scripted Runtime over the same PostgreSQL Case. |

## Rereview and final remediation

A fresh Terra rereview confirmed those four findings closed and found one new
Important issue: Runtime callers could supply adapter/storage profile labels
that contradicted the actual injected dependencies, which could falsify
operation evidence or skip readiness.

The override parameters were removed. `ThinAgentRuntime` now derives the
profile solely from its actual Fast/Slow adapters and repository. Regressions
prove that a non-memory repository cannot masquerade as memory, a non-scripted
adapter cannot be recorded as scripted, and the removed override keywords are
rejected.

## Final rereview

The fresh final rereview returned **Approve** with no unresolved Critical,
Important, or Minor finding. It independently passed 16 Phase 04D tests, the
local diagnostic profile, 62 combined Phase 04A/04B/04D regressions, affected
Ruff, strict mypy, four Phase 04C configuration/storage-boundary regressions,
and the staged diff check.

Sol separately passed the real disposable PostgreSQL gate with 24 tests after
each material review remediation. The final repository preflight, Harness
closeout, hosted CI, GitGuardian, PR, merge, and branch cleanup remain outside
this review artifact and are recorded by their authoritative later evidence.

## Authority and scope conclusion

The approved slice observes and probes the existing local control plane. It
does not authorize or implement Temporal, real Providers or tools, external
side-effect recovery, model promotion/training, authentication, channels,
voice, deployment, release, production capacity, or production readiness.
