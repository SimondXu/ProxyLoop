# Phase 04A — Thin Agent Runtime

**Status**: Complete; independently approved. Activated from the merged Phase
03A1-R/V gate (`e501e0f`, PR #11) on
`feat/phase-04a-thin-agent-runtime`.

## Objective

Assemble the existing contracts, Case coordinator, deterministic Router,
typed Fast/Slow adapters, approval policy, fictional Provider simulator,
Evidence, and completion verifier into one small, runnable local Agent loop.
The implementation is simulator-backed and must keep deterministic
authorization, side effects, business truth, and completion outside the
models.

## In scope

- a minimal FastAPI control-plane surface under `runtime/services/api`;
- an explicit replaceable in-memory Case store/repository interface;
- create and read one fictional telecom Case;
- append model-visible and fictional-Provider events;
- project a version-pinned Case Context Snapshot;
- route each turn through the existing typed Router -> Slow/Fast interfaces;
- deterministic policy and proposal validation;
- current version-bound approval for consequential actions;
- at-most-once execution of an approved fictional-Provider capability;
- recording Provider-result Evidence and deterministic completion validation;
- one reproducible multi-turn integration test covering approval wait,
  continuation, and a verified terminal outcome;
- one authoritative explicit offer-compliance policy shared by the Provider
  verifier and scripted oracle where the existing hidden predicate disagreement
  is exercised. This is a small runtime policy task, not a new evaluation
  subsystem.

## Acceptance criteria

1. A consumer can create and read one fictional telecom Case through the local
   API or an equivalent local CLI boundary.
2. A message and Provider event advance the Case through Router -> Slow/Fast
   and deterministic validation using typed interfaces.
3. The Case exposes a version-pinned Context Snapshot, and stale proposals or
   stale approval decisions cannot authorize consequential work.
4. A consequential proposal cannot execute without a current, version-bound
   approval for the same Case and material terms.
5. An approved fictional-Provider action executes at most once for its
   idempotency key and records immutable Evidence.
6. Completion remains `not_done` until the deterministic verifier accepts
   current Evidence and current Case state.
7. One integration test demonstrates the complete multi-turn path, including
   an approval wait, continuation, at-most-once execution, and verified
   terminal outcome.
8. Existing Phase 03A1-R/V artifacts remain byte-for-byte immutable and
   `make preflight` passes at the Phase 04A gate.

## Explicitly out of scope

- additional model evaluation, r6/r7 reports, high-reasoning comparisons, or
  prompt-optimization loops;
- SFT, QLoRA, DPO, RL, training-data expansion, or model training;
- PostgreSQL, Temporal, cross-process durability, worker deployment, vLLM,
  or production serving;
- real tools or Providers, external channels, authentication, voice, or
  consumer PII;
- web UI, cloud deployment, release publication, or production claims;
- broad contract/schema redesign beyond what is required to connect the thin
  loop to existing canonical types.

## Required boundaries

- Use fictional Provider simulator capabilities only.
- Use injected typed Fast/Slow adapters; do not dispatch a model or external
  API as part of this phase.
- Keep FastAPI/framework code at the service boundary. Domain contracts,
  policy, orchestration, and simulator logic must remain independently
  testable.
- Keep the in-memory store behind a replaceable interface so PostgreSQL and a
  durable workflow remain later integration steps.
- Do not modify or regenerate the historical Phase 03A1 artifacts as part of
  this phase.

## Current implementation-gate evidence

- Luna's runtime-focused report records 10 Phase 04A tests passed, API Ruff
  and mypy passed, and `make preflight` with Runtime 162 and ML 115 tests.
- Luna's policy-focused report records 86 relevant tests passed, mypy over 21
  files and Ruff passed, benchmark/hosted-rerun/validity-smoke checks passed,
  and `ml/uv.lock` byte-identical to `HEAD`.
- Sol's focused integration run records 24 combined tests passed.
- Sol's final `make preflight` records Runtime 162 and ML 115 tests passed,
  together with contracts, artifacts, layout, locks, offline pnpm, and
  Compose checks passed.
- Sol's `git diff --check` passed. The canonical r4 and r5 artifact SHA-256
  values remain `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`
  and `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`;
  no `ml/` or historical artifact diff was observed.
- Terra's first independent review returned Request Changes with two Critical,
  four Important, and one Minor finding. Remediation completed, and the
  durable review at `harness/code_review/phase-04a-thin-agent-runtime.md`
  records Terra's final independent Approve after a focused 67-test review
  and an additional execution-claim CAS injection check.

## Verification and stop condition

The implementation gate, independent review, and repository-native
`make preflight` are recorded in `harness/build-log.md`; the durable review
records Terra's final approval. Phase 04A is complete at the local runtime
gate. No subsequent implementation phase is active. Do not activate training,
databases, Temporal, real tools, deployment, channels, voice, or UI without a
new explicit gate.
