# Phase 03A1 Baselines Independent Review

Date: 2026-08-24

Reviewer: independent Terra high, read-only

Final recommendation: **Approve**. No unresolved Critical or Important finding.

This approval covers the final Terra-backed Baselines runner, deterministic
evidence boundaries, local Qwen and hosted model artifacts, hosted-call safety
controls, offline replay gate, and recorded failure slices. It confirms that the
five frozen conditions ran and are reproducible; it does not claim model-quality
success, independently prove the third-party proxy's physical backend, or
authorize Phase 03B.

## Scope Reviewed

- ML-only Qwen MLX and OpenAI Responses adapters;
- strict semantic Fast/Slow output schemas and deterministic canonical compilers;
- frozen Harness input binding and held-out/safety episode coverage;
- local Qwen provenance, prompt/output evidence, result classification, and failure slices;
- Slow-off ablation and scripted-oracle ceiling;
- hosted model identity, token/call/cost ceilings, retry policy, credential gate, and failure handling;
- committed report shape, provenance, fingerprints, offline replay, and tamper regressions;
- dependency isolation and prohibited training/product scope.

## Initial Findings

The initial review requested changes for one Critical and four Important findings:

- the OpenAI SDK retained its default retry behavior, invalidating the one-logical-call budget assumption;
- an exception after provider dispatch could be reported as not-run with zero calls and zero cost;
- model runs were not rebound to the live fixtures behind the committed Harness fingerprints;
- Qwen provenance trusted CLI revision declarations rather than the actual checkpoint, tokenizer, and chat-template files;
- the offline artifact gate could be bypassed by refingerprinting fabricated prompts, model calls, outputs, or cost.

## First Remediation

- Configured the OpenAI client with `max_retries=0` and added a constructor regression.
- Recorded every started provider request as hosted-call evidence. A response without auditable usage becomes `FAILED_PROVIDER_CALL`, `actual_cost_unknown`, incomplete cost accounting, and a terminal condition failure.
- Rebuilt the live Harness report before checkpoint loading or provider calls and compared its manifest, episode, and ceiling fingerprints with committed artifacts.
- Removed CLI revision overrides and attested every file in the frozen Qwen snapshot plus the tokenizer set and chat template.
- Added offline prompt reconstruction, semantic Fast/Slow recompilation, model/call/usage/cost reconciliation, exact provenance checks, and tamper regressions.

## Second Rereview Findings

The first remediation closed the original five findings. The rereview found no Critical issue but retained two Important blockers:

- after an unknown-cost failure stopped the Fast-plus-Slow condition, the runner still proceeded to the frontier-reference condition;
- failed hosted conditions were skipped by offline replay, so attempted-call evidence and unknown cost could still be fabricated.

## Final Remediation

- Hosted conditions now run in a fixed sequence. If the first condition fails with incomplete cost accounting, the frontier-reference condition becomes `not_run_budget_rejected` with zero calls and zero evaluated episodes.
- A two-client regression proves one attempted call on the failing adapter and zero calls on the second adapter.
- Offline replay now covers failed conditions, reconstructs the failed Slow or Fast request, checks prompt and schema fingerprints, requires exactly one final unknown-cost attempt, reconciles model-call counts and known costs, and rejects continued hosted work.
- Refingerprinted model-call-count and unknown-cost mutations fail the artifact gate; a valid failed-attempt artifact replays successfully.

## Final Verification

Root and the independent reviewer each ran `make preflight` on the final remediated worktree. Both runs passed with:

- 135 runtime/contract/integration tests;
- 42 ML tests;
- Ruff formatting and lint;
- mypy for runtime and ML;
- canonical contract generation drift and TypeScript compilation;
- Phase 01B benchmark, Phase 02 data-pilot, Phase 03A1 Harness, and Phase 03A1 Baselines artifact gates;
- layout, runtime/ML lock checks, frozen offline pnpm lock, Python compilation, Docker Compose configuration, and Git diff checks.

No hosted/API call was made during the original review. A later compatibility
probe and the authorized full run are recorded in `harness/build-log.md`; their
implementation and artifacts received the final rereview below. Training, data
expansion, product services, external channels, UI, deployment, and Phase 03B
remain outside scope.

## Terra-Backed Final Rereview

The 2026-08-24 rereview inspected the frozen 29qg Chat Completions transport,
Terra model and returned-snapshot validation, zero-retry and secret handling,
Qwen-plus-Terra and Terra-reference results, cost-accounting semantics,
artifact/replay truthfulness, completion-readiness meaning, evaluator leakage,
and deterministic authority boundaries.

The rereview initially requested changes for one Important finding and no
Critical finding: every report used a fixed 2026-08-23 `generated_at` value even
though the hosted run occurred on 2026-08-24. Because the report fingerprint
covered this value, the evidence was reproducibly bound to an untrue creation
time.

The fixed constant was removed. Report composition now records the actual
second-precision UTC creation time, the schema requires the UTC `Z` format, and
a regression binds the timestamp through the report fingerprint. The committed
full-run artifact records its final write time, `2026-08-24T05:24:05Z`, and
passes the offline artifact/replay gate.

After remediation, the independent reviewer returned **Approve**, with no new
Critical or Important finding. Root and the reviewer each ran `make preflight`
successfully: 135 runtime/contract/integration tests and 43 ML tests passed,
together with format, lint, mypy, contract/type drift, artifact replay, layout,
lock, offline pnpm, compile, Compose, and Git diff checks. The reviewer made no
hosted request.

The reported `$1.580080` is actual returned token usage multiplied by frozen
conservative accounting rates, not a provider invoice. The reviewer treated the
existing field name as a non-blocking clarity improvement because the phase
contract and build log disclose that basis and no current consumer presents it
as billed cost. The repository validates returned Terra-family metadata and
rejects explicit remapping; it does not independently attest the proxy's hidden
physical backend.
