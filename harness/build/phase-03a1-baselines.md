# Phase 03A1-B — Untuned Model Baselines

**Status**: Complete; frozen model matrix executed, independently reviewed, and
PR #9 CI/GitGuardian gates passed.

**Activation**: Explicitly approved by the user on 2026-08-23 as the second
sequential Phase 03A1 pull request, after the deterministic Harness was squash
merged as `e08c9b6` through PR #8. Active branch:
`experiment/phase-03a1-baselines`.

## Objective

Measure untuned Fast and Slow model behavior through the already validated
multi-turn Harness, so failure slices—not an assumed training plan—determine
whether a separately gated Phase 03B is justified.

## In Scope

- an ML-only evaluation package with typed Fast and Slow adapter seams;
- a locally runnable, untuned Qwen Fast adapter;
- a hosted OpenAI-compatible Terra reference adapter behind the same typed seams;
- the five frozen report conditions below over immutable Phase 03A1 manifests;
- committed, redacted evaluation records and a deterministic offline artifact
  validator that CI can run without models, credentials, or network access;
- schema, routing, policy, safety, end-to-end, latency, token, cost, and failure
  slice reports;
- exact model, checkpoint, quantization, prompt, adapter, generation, host-class,
  and artifact fingerprints.

## Non-Goals

- SFT, QLoRA, DPO, RL, prompt tuning, few-shot optimization, hyperparameter
  search, teacher-backed generation, public-data ingestion, or project-data
  expansion;
- changing Phase 02 from `pending_human` or `training_ready=false`;
- promoting a model to serving or claiming production quality;
- product services, durable workflow, database, API, UI, channels, credentials
  in the repository, real Provider contact, deployment, or release publication;
- letting any model authorize or execute a capability or decide completion.

## Frozen Evaluation Conditions

1. `scripted_oracle_ceiling` reuses the committed deterministic Harness ceiling
   as environment validity evidence. It is not a learned-model result.
2. `untuned_fast_reference_strategy` runs untuned Qwen as Fast with one generic,
   versioned reference Strategy Packet frozen before test evaluation. It measures
   Fast policy isolation and is not labeled end-to-end Slow-off.
3. `untuned_fast_slow_off` provides no Slow adapter and no synthetic strategy.
   Mandatory Slow routes must end as typed `slow_unavailable` non-completion;
   Fast cannot bypass the Router.
4. `untuned_fast_frontier_slow` runs Qwen Fast with the frozen frontier Slow
   configuration. `frontier_reference` uses the same frontier configuration for
   both typed model seams. Deterministic Router, policy, approval, Executor,
   Evidence, and Verifier authority remain unchanged in both conditions.

## Frozen Model and Runtime Configuration

- Fast source model: `Qwen/Qwen3-4B-Instruct-2507`, Apache-2.0, non-thinking
  instruct checkpoint. The local Apple-Silicon run may use the derived
  `mlx-community/Qwen3-4B-Instruct-2507-4bit` checkpoint only when its source
  revision, derived revision, tokenizer/chat-template fingerprint, and 4-bit
  quantization are recorded. Results must be labeled `quantized_untuned`, never
  silently presented as native-weight results.
- Frontier model: `gpt-5.6-terra` through the user-approved
  `https://29qg.com/v1` OpenAI-compatible Chat Completions endpoint, with frozen
  reasoning effort and structured-output schema. The returned snapshot must be
  `gpt-5.6-terra` or a versioned suffix of that model; any proxy remapping is a
  failed result. Sol is not part of this baseline.
- Actual checkpoint revisions are pinned from downloaded/provider metadata, not
  guessed in this contract.
- Decoding is deterministic where the provider/runtime supports it. Unsupported
  seed or sampling controls are recorded rather than simulated.
- Model SDKs and MLX imports are lazy and contained under `ml/evaluation`; they
  must not enter `runtime/packages/agent_core` or its dependency lock.

## Isolation and Authority Rules

- Development inputs may shape a generic prompt/schema/reference strategy.
  Family/entity/provider-held-out and safety episodes may never shape them.
- Manifest-private Family, Entity, Provider-assignment, reference-action,
  expected-outcome, reward, evaluator, and oracle fields are evaluator-only and
  never enter a model request.
- Safety Families remain safety-only and training-ineligible.
- Raw hidden chain-of-thought is neither requested nor persisted. Records contain
  structured output, bounded response text, usage, timing, result status, and
  fingerprints only.
- Invalid JSON/schema output is measured as failure. The evaluator may parse a
  provider's structured-output envelope but may not silently repair semantic
  output or replace it with scripted success.
- Models emit strict semantic proposals only. Trusted adapter compilers bind
  infrastructure-owned identifiers, timestamps, and current input pins before
  canonical validation; this deterministic binding is not model-output repair.
- All capability proposals remain inert until the existing deterministic policy,
  approval, and simulator-only Executor accept them. Only Evidence-backed
  deterministic verification can produce completion.

## Cost and External-Call Gate

- Local public-checkpoint download/inference records bytes, elapsed time, and
  checkpoint provenance; it has no API cost.
- Before hosted calls, the runner computes a conservative maximum from frozen
  episode count, input/output token caps, retry cap, and frozen quota-accounting
  rates. Calls stop before the configured USD ceiling.
- The 29qg response exposes token usage but no invoice amount. Reported hosted
  cost is therefore actual returned usage multiplied by the frozen conservative
  `$4/M` input and `$20/M` output quota-accounting rates; it is explicitly an
  accounted estimate, not a provider invoice claim.
- Hosted credentials come only from `PROXYLOOP_FRONTIER_API_KEY` in the process
  environment, are never printed, serialized, committed, or recovered from
  unrelated application state.
- Missing credentials or unavailable model access is reported as
  `not_run_missing_credentials` or `not_run_model_unavailable`, never as pass,
  zero score, or a synthetic frontier result.

## Measurements and Failure Slices

Each condition reports observed counts/rates for schema validity, pin validity,
Fast `action_intent=null`, Router agreement, forbidden capability proposals,
authorization/approval/material mismatches, private-field leakage, duplicate
execution, completion/non-completion, false completion, end-to-end validity,
latency percentiles, tokens, and cost. Failures are classified at least by
condition, split kind, safety/non-safety, route outcome, adapter result, and
deterministic verifier reason. Evaluator-only slice identifiers never enter
model-visible inputs.

## Acceptance Criteria

1. Repository status records PR #8 / `e08c9b6` complete and makes 03A1-B the
   sole active phase; 03B remains inactive.
2. Red tests precede implementation and prove absent adapters/artifacts fail the
   gate for the intended reasons.
3. Model-specific dependencies and adapters remain in the ML environment, use
   lazy optional imports, and do not change deterministic runtime dependencies.
4. Prompt builders accept only typed Fast/Slow views and leakage tests prove
   evaluator/private fields cannot reach serialized requests.
5. Qwen outputs compile only through canonical Fast validation; invalid output,
   stale pins, forbidden Action Intent, and unsafe completion text are recorded
   and cannot cause a side effect or completion.
6. Slow and frontier Fast outputs compile only through canonical validation and
   the existing coordinator/Router authority boundaries.
7. All five frozen report conditions are represented honestly. A missing hosted
   credential blocks the two frontier-backed executions and cannot be converted
   into a passing artifact.
8. Every frozen evaluation episode runs against immutable 03A1 manifests with
   no family/entity/provider/safety leakage or test-derived prompt/reference
   strategy.
9. Reports include reproducibility metadata, structured failure slices, latency,
   token use, actual/estimated cost, and explicit not-run reasons.
10. CI/preflight validates committed result schemas, fingerprints, provenance,
    redaction, condition coverage, and truthful run status without downloading or
    calling a model.
11. Untuned model quality is not a phase pass criterion. The gate passes only if
    the Harness accurately detects, classifies, and reproduces observed model
    failures and the environment ceiling remains valid.
12. Focused checks and `make preflight` pass; the full diff and result evidence
    receive independent Terra review; accepted findings are remediated and exact
    commands/outcomes are appended to `harness/build-log.md`.

## Stop Condition

After Qwen/frontier runs, independent review, CI/GitGuardian, and squash merge,
stop with failure slices and an evidence-based recommendation. Do not train,
expand data, activate Phase 03B, serve a model, or implement product Agent
services without a new explicit user gate.
