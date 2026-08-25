# Phase 04B — Model-backed Thin Agent Runtime

**Status**: Local implementation gate complete and independently approved;
PR/CI/GitGuardian/squash-merge integration pending. Explicitly approved on
2026-08-25 from synchronized `main` at `75974da` on
`feat/phase-04b-model-backed-runtime`.

## Objective

Run the Phase 04A `ThinAgentRuntime` through one typed, runtime-owned,
OpenAI-compatible Fast/Slow adapter while retaining the fictional Provider and
the existing deterministic Router, policy, version-bound approval,
`CapabilityExecutor`, Evidence, and completion verifier as the only authority
for routing, authorization, side effects, business truth, and completion.

## Frozen interface and dependency seam

- The existing `FastAdapter` and `SlowAdapter` protocols plus canonical
  `FastModelView`, `SlowWorkRequest`, `FastTurnDecision`, and `SlowWorkResult`
  contracts are the external seam. Do not create a registry, plugin system, or
  provider-neutral model gateway.
- Implement one concrete OpenAI-compatible Chat Completions Structured Outputs
  path in a runtime-owned package. The production client must use an explicit
  timeout and zero SDK retries; tests inject a fake transport and make no
  network request.
- `runtime/services/api` may depend on the runtime-owned adapter package.
  Runtime packages and services must not import `ml/evaluation`.
- `ml/evaluation/openai_frontier.py` remains evaluation-only. It binds frozen
  Phase 03A1 provider/model, budget, cost, attestation, replay, and artifact
  behavior and is not the production-runtime adapter.
- Keep any runtime model-facing schema and deterministic compiler local to the
  adapter package. The shared seam is the canonical runtime protocol, not the
  historical evaluation prompt implementation; do not move or modify Phase
  03A1 evaluation code or artifacts to remove small intentional duplication.
- Scripted adapters remain the default. Model-backed mode is enabled only by
  explicit constructor injection or explicit server configuration. No code
  reads `.env`; configuration comes from constructor values, CLI arguments, or
  the process environment.

## In scope

- one typed OpenAI-compatible adapter satisfying both existing Fast and Slow
  protocols;
- strict model-facing Pydantic Structured Outputs and deterministic compilation
  into canonical, version-bound proposals;
- exact requested/returned model-family metadata validation;
- explicit safe failures for timeout, transport failure, invalid/refused or
  missing structured output, wrong/missing model metadata, and stale input
  pins;
- runtime handling that stops a failed or rejected model result before an
  approval is created or a fictional Provider action is executed;
- mocked-transport tests for successful Slow initialization and Fast turn work,
  plus every required failure class;
- a runnable local server command with scripted mode as its default;
- one localhost TCP/HTTP black-box smoke test that starts the real server
  command in scripted mode and exercises create/read/event/approval to verified
  terminal completion.

## Acceptance criteria

1. A runtime-owned OpenAI-compatible adapter satisfies the existing typed Fast
   and Slow protocols without any Runtime-to-ML import.
2. A fake-transport integration test creates a Case through model-backed Slow,
   advances a turn through model-backed Fast, and reaches the existing pending
   approval state using canonical typed outputs.
3. Models remain proposal-only: accepted model output cannot directly authorize
   approval, execute the fictional Provider, create Evidence, or decide final
   completion.
4. Timeout, transport failure, invalid/refused/missing structured output, and
   wrong/missing response-model metadata produce stable typed safe failures;
   raw provider messages, request bodies, headers, credentials, and arbitrary
   exception text are not returned by the HTTP surface.
5. Stale Fast or Slow pins are rejected against current state and cannot create
   approval state, execute a Provider capability, append completion Evidence,
   or advance authoritative completion.
6. The OpenAI-compatible client has an explicit timeout and `max_retries=0`.
   Automated tests use an injected fake transport and record zero external
   dispatches.
7. `ThinAgentRuntime()` and the ordinary server command still default to the
   scripted adapters. Model-backed mode requires explicit injection or explicit
   configuration and rejects incomplete configuration before serving.
8. A documented local server command binds localhost and a black-box test uses
   real TCP/HTTP, not ASGI in-process transport, to complete the fictional
   scripted flow.
9. Focused tests and repository-native `make preflight` pass; `ml/` and all
   historical Phase 03A1 artifacts have no diff.
10. An independent Terra reviewer approves the final bounded diff after any
    accepted findings are remediated, and durable review/build-log evidence is
    committed before publication.
11. The final PR passes CI `phase-gate` and GitGuardian, is squash merged, and
    its fully merged short branch is safely cleaned before the phase stops.

## Explicitly out of scope

- any real model/API smoke without a new explicit user confirmation;
- Phase 03A1 continuation, r6/r7, matrix expansion, prompt optimization, or
  modification/regeneration of historical evaluation artifacts;
- training, SFT, QLoRA, DPO, RL, data expansion, or model promotion;
- PostgreSQL, Temporal, cross-process durability, workers, or outbox work;
- a multi-provider registry, plugin system, generic model gateway, routing by
  price/quality, fallback models, or automatic retry/failover;
- real tools or Providers, authentication, channels, voice, UI, deployment,
  release, credentials, consumer PII, or production claims.

## Verification plan

1. Red: architecture/dependency tests prove the runtime adapter, explicit
   server command, and model-failure boundary do not yet exist.
2. Green: implement the smallest runtime-owned adapter and explicit server
   wiring; use fake transport only.
3. Focused: run the new adapter, runtime failure, and localhost black-box tests,
   then affected Ruff and strict mypy checks.
4. Broad: run `make preflight`, `git diff --check`, and a scope audit proving
   no `ml/`, historical evaluation artifact, `.env`, credential, deployment,
   training, database, Temporal, channel, voice, or UI diff.
5. Review: obtain independent Terra review, remediate accepted findings with
   the implementer, rerun affected and broad gates, and write durable evidence.
6. Publish: commit, push, open the bounded PR, observe CI/GitGuardian, squash
   merge, verify synchronized clean `main`, safely clean the merged branch, and
   stop. Do not activate Phase 05 or any other phase.

## Current local-gate evidence

- Luna's initial architecture Red produced two failures and one pass because
  the runtime adapter package and server surface did not exist.
- The first implementation passed its focused suite and full preflight. Sol's
  integration review then found that failed or stale Slow work could leave a
  half-created Case, that stale Slow/refusal/client-construction regressions
  were incomplete, and that Runtime used a second OpenAI SDK behavior surface.
- Luna remediated those accepted findings: Slow success and coordinator
  acceptance now precede repository creation; stale Slow, refusal, explicit
  timeout/zero-retry client construction, and no-half-created-Case regressions
  were added; Runtime now pins the same `openai==2.51.0` path already validated
  by the repository.
- Terra's initial independent review returned Request Changes with one
  Important finding: non-finite timeout values could pass configuration. Luna
  added finite-positive validation at both process and adapter entrances plus
  regressions for `nan`, `inf`, and `-inf`.
- Terra's final read-only rereview returned Approve with no remaining Critical,
  Important, or Minor finding and independently passed 32 focused tests plus
  the complete repository preflight.
- Sol's pre-rereview focused run passed 16 tests and its full preflight passed
  with Runtime 178 and ML 115 tests. After final remediation and durable
  evidence, Sol's focused Phase 04B run passed 22 tests and its final complete
  preflight passed with Runtime 184 and ML 115 tests.
- No external model/API call occurred. No credential or `.env` was read.
  `ml/`, `data/evaluation/`, and historical Phase 03A1 artifacts have no diff.
- Durable independent review:
  `harness/code_review/phase-04b-model-backed-runtime.md`.
- PR #13 initial head `bfe9915` passed the hosted `phase-gate` and GitGuardian
  checks. Sol reviewed the complete 29-file PR diff and approved squash merge
  subject to this evidence-only commit passing the same hosted checks again.
- No implementation phase is active after Phase 04B. No next phase is
  activated by this closeout.
