# Phase 03A1-R — Hosted Baseline Reliability Rerun

**Status**: Complete with the corrected full hosted matrix. The canonical r4
artifact is valid, `phase_completion_ready=true`, and Phase 03B remains
inactive pending a separate model-quality decision.

**Base**: Phase 03A1-E was squash merged as `a91943c` through PR #10. Its r2
source evidence and r3 offline attribution correction are immutable inputs.

## Objective

Prove that the configured Terra compatibility endpoint can return auditable
structured responses, usage, returned model metadata, and sanitized error
provenance under zero-retry execution; then rerun the four frozen medium/high
hosted conditions into a separately versioned r4 report whose complete failure
slices can support a later human decision about Phase 03B.

## In Scope

- a two-call, minimal structured-output Provider probe at medium and high
  reasoning effort;
- response ID/model, input/output/reasoning usage, latency, conservative cost,
  and sanitized Provider error class/status/request-ID/code/type evidence;
- a new `phase-03a1-r4-hosted-rerun-v1` report that binds immutable r2 and r3
  report fingerprints and timestamps;
- reuse of the three deterministic r3 conditions without local model reruns;
- fresh Qwen Fast + Terra Slow medium/high and Terra reference medium/high
  execution over the unchanged r2 fixtures, prompts, schemas, caps, and
  evaluator;
- offline replay, source binding, dispatch accounting, tamper checks,
  independent review, repository preflight, PR/CI/GitGuardian, squash merge,
  and post-merge verification.

## Frozen Decisions

1. R2 and r3 files, bytes, timestamps, fingerprints, raw outputs, and call
   evidence are never rewritten. R4 stores their fingerprints and timestamps.
2. The Provider probe uses no evaluation episode or Consumer/Provider payload.
   It requests a fixed tiny strict JSON object twice, once at medium and once at
   high reasoning effort, with zero SDK retries and a separately accounted cap.
3. Probe readiness requires two successful responses with returned model and
   response IDs, positive input/output usage, and complete usage-accounted cost.
   Any failed or unauditable probe prevents every matrix call.
4. Sanitized errors may include only exception class, HTTP status, request ID,
   and provider code/type/parameter. Provider messages, request bodies, headers,
   credentials, and raw exception representations are forbidden.
5. The r4 matrix reuses the r3 evaluator attribution and the unchanged r2
   fixtures/configuration. It does not tune prompts, schemas, caps, or scenarios
   after any probe or model dispatch. The probe artifact fingerprints the exact
   adapter, evaluator, replay, Qwen, dependency-lock, and command files; the
   matrix refuses to start if any of them drift.
6. Hosted execution order remains Qwen+Terra medium, Qwen+Terra high, Terra
   reference medium, Terra reference high. A started call with unknown actual
   cost globally aborts all later conditions with zero calls.
7. `phase_completion_ready=true` means both probes and all seven evaluation
   conditions are complete and replayable. It is not a model-quality or
   training-readiness claim.

## Acceptance Criteria

1. Activation made 03A1-R the only active phase; closeout leaves no active
   implementation phase and keeps 03B inactive.
2. Red tests fail because the new r4 artifact, probe interface, source binding,
   and Make gate do not yet exist.
3. Adapter tests prove zero retries and safe structured error extraction without
   request/header/credential persistence.
4. Probe tests prove medium/high ordering, strict output validation, auditable
   usage/model/response metadata, bounded cost, and fail-closed matrix blocking.
5. R4 tests prove immutable r2/r3 source binding, unchanged three local
   conditions, exact four hosted conditions, dispatch reconciliation, offline
   semantic replay, execution-contract drift detection, report fingerprint
   drift detection, and false-readiness rejection.
6. Before external calls, r2/r3 checks, source hashes, scripts, prompts, schemas,
   model, reasoning efforts, token/call caps, and the total maximum accounting
   ceiling are frozen and pass offline checks.
7. The complete hosted matrix runs or reports an honest terminal Provider or
   budget blocker. No failure is relabeled as not-run after dispatch.
8. Reports retain the 29qg cost-estimate/not-invoice and hidden-backend-not-
   independently-verified disclosures.
9. Focused checks and `make preflight` pass; independent review has no unresolved
   Critical/Important finding; exact commands/results are appended to the build
   log; PR CI/GitGuardian pass before squash merge.
10. No SFT, QLoRA, DPO, RL, training-data expansion, serving, product Agent,
    database, real Provider/tool, channel, UI, deployment, release, credential
    persistence, or Phase 03B work occurs.

## Stop Condition

After the r4 evidence is independently reviewed and integrated, stop and report
the complete failure slices plus the explicit Phase 03B decision gate. Do not
start training automatically.

## Terminal Outcome

- The first locally injected credential attempt used the user's colon-delimited
  `api:<secret>` line as a whole token and received HTTP 401. That launcher
  mistake did not reach inference. Its exact artifact is preserved separately
  as `phase-03a1-r4-attempt-01-auth-misconfigured.json`.
- With the value correctly extracted, medium and high probes both succeeded on
  `gpt-5.6-terra-2026-07-09` with response IDs and complete token usage.
- The first matrix attempt used a Pydantic discriminated union that emitted
  unsupported `oneOf` and `discriminator` keywords. Both official OpenAI Terra
  and 29qg rejected that exact Schema. Its valid failure artifact is preserved
  separately as `phase-03a1-r4-attempt-02-unsupported-schema.json`.
- Replacing only that model-facing union representation with `anyOf` preserved
  strict semantic validation. Official Terra accepted the corrected Schema,
  and a subsequent 29qg Terra parse returned a complete typed result.
- The canonical r4 then completed both probes and all four frozen hosted
  conditions: 148 new external dispatches including probes, 3,114,128
  usage-accounted microusd, complete accounting, and
  `phase_completion_ready=true`. The report passes offline replay and tamper
  validation; r2/r3 remain byte-identical.
- Evidence completeness does not imply model quality. The completed failure
  slices remain the required input to a separate human Phase 03B decision.
