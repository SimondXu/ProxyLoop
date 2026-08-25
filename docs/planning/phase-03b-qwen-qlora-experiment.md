# Proposed Phase 03B Qwen3-4B QLoRA Experiment

## Status

Proposed handoff only. This document does not activate Phase 03B and does not
authorize training, model downloads or calls, data expansion, teacher
generation, hosted spend, new evaluation artifacts, or changes to historical
Phase 03A1 evidence. A fresh explicit user gate is required.

## Decision intent

ProxyLoop intends to run one controlled post-training experiment on
`Qwen/Qwen3-4B-Instruct-2507` so the project can measure the same Fast Model
before and after QLoRA/SFT. The readiness gate decides whether the data and
evaluation are valid enough to begin; it does not reopen the question of
whether the project should ever attempt fine-tuning. The smoke gate decides
whether to expand data or training. The final held-out gate decides whether a
tuned checkpoint is promoted.

This separates three claims:

- **Planned**: run a bounded QLoRA smoke after readiness passes.
- **Measured later**: whether tuned Qwen improves over the frozen untuned
  baseline.
- **Not assumed**: that tuning must improve, should scale, or deserves serving
  promotion.

Pine's public technical account supports the hypothesis that a dedicated Fast
Model can learn Fast/Slow coordination and high-frequency task behavior through
SFT/RL, but it does not disclose a reproducible ProxyLoop training recipe or
independently prove improvement for Qwen3-4B. Pine evidence motivates the
experiment; ProxyLoop's held-out comparison owns the conclusion.

External hypothesis evidence, treated as first-party/self-reported rather than
independent validation:

- Bojie Li, Pine AI co-founder and chief scientist, “Effective Agents: Real-Time
  Interaction with the Environment, Learning from Experience”:
  https://01.me/en/2025/06/agent-learn-from-experience/
- Pine's published tau2 voice trajectories and reported results:
  https://huggingface.co/datasets/pine-ai/pine-realtime-1.0-preview-tau2-voice-trajectories

## Current repository evidence

- Phase 02 produced 128 accepted deterministic one-turn trajectories across
  32 scenarios and 16 families, split 80 train / 24 development / 24 test.
- The 16-record cross-family review sample remains `pending_human`; the quality
  report therefore remains `training_ready=false`.
- Phase 03A1 established the untuned model/evaluation infrastructure, but the
  original hosted r4 comparison is not a valid training baseline because
  model-view and prompt-contract mismatch affected attribution.
- Phase 03A1-V's six-episode diagnostic reached 5/6 end-to-end validity after
  prompt/input parity. Its remaining fee case exposed an evaluator predicate
  absent from the visible goal, so it is not yet an unambiguous model-capability
  failure.
- Phase 04B added a runtime-owned typed OpenAI-compatible adapter. Runtime and
  ML remain separate dependency environments, and models remain proposal-only.

Authoritative inputs:

- `harness/build/phase-02-data-factory.md`
- `data/manifests/phase-02-quality-report.json`
- `data/samples/phase-02-review-sample.json`
- `harness/build/phase-03a1-baselines.md`
- `harness/build/phase-03a1-evaluation-validity-smoke.md`
- `harness/build/phase-04b-model-backed-runtime.md`
- `docs/decisions/2026-08-23-fast-slow-orchestration.md`

## Proposed staged experiment

### Gate 0 — Readiness and human review

Before training:

1. Complete the 16-record Phase 02 human review using the committed annotation
   guide. Preserve individual review evidence and rejection reasons.
2. Recompute or regenerate Phase 02 quality metadata only through an explicitly
   approved, versioned phase action. Do not edit `training_ready` by hand.
3. Classify observed failures into evaluator/goal visibility, prompt/schema,
   simulator/capability, data-quality, transport, and learnable Fast Model
   slices. Only the final category justifies training examples.
4. Resolve and version the fee-total-cost evaluator ambiguity before freezing
   the comparison. Historical r4/r5 artifacts remain immutable.
5. Freeze the base checkpoint, tokenizer, non-thinking mode, model-facing view,
   prompt/schema/compiler, decoding settings, data manifests, split hashes,
   metrics, safety gates, and hardware/software metadata.
6. Keep test records sealed. Use train for optimization and development for
   configuration decisions. Perform a power analysis before any expanded final
   held-out claim.

Readiness passes only when human review and automated audits support a truthful
training-ready dataset, the baseline path is evaluation-valid, and the exact
training target remains inside the bounded Fast responsibilities.

### Gate 1 — Local QLoRA smoke

Use the reviewed 80-record training split for the smallest reproducible local
QLoRA run. The development split may be evaluated; the test split remains
sealed. The smoke must record:

- exact base and adapter identities, configs, seeds, package/hardware metadata,
  wall time, peak memory, and checkpoint hashes;
- train/development loss and overfitting signals;
- structured-output and canonical semantic validity;
- dialogue-act, fact-update, reasoner-request, and completion-candidate metrics;
- unsupported facts, false completion, policy/PII violations, stale pins, and
  authority-boundary violations;
- P50/P95 latency and total completion time on the same local inference path.

The smoke may justify data/training expansion only if it is reproducible, shows
development signal beyond memorization, and does not regress any hard safety
gate. A failed smoke is a valid terminal result and must not be hidden by
changing the held-out set or silently widening the data.

### Gate 2 — Gap-driven expansion and final comparison

If Gate 1 passes, expand project-specific training data only for measured
residual Fast failure slices. Preserve family/entity/provider separation,
source/license/provenance, content hashes, PII checks, deduplication, and
cross-split leakage checks. Do not train on Pine/tau2 or ProxyLoop final-test
trajectories used for the headline result.

The causal comparison is:

| Arm | Checkpoint | Inference contract | Evaluation |
|---|---|---|---|
| A | Untuned Qwen3-4B | Frozen final view/prompt/schema/compiler/decoding | Frozen held-out manifest |
| B | Same Qwen3-4B plus QLoRA | Identical to Arm A | Same frozen held-out manifest |

The old r4 0/6 result is diagnostic history, not Arm A. Both arms must run
through the corrected, frozen evaluation-valid path. Optional model-size or
architecture challengers require a separate matrix decision and cannot replace
the same-model before/after comparison.

### Gate 3 — Adoption decision

Report schema/semantic validity, end-to-end success, failure slices,
confidence intervals, latency/cost, and source/data-size ablations. Freeze the
practical improvement threshold after pilot power analysis and before full
training. The specification's roughly five-point target remains provisional.

Promotion requires useful family-held-out improvement with:

- zero increase in false completion;
- zero policy, PII, stale-pin, or authority-boundary violation;
- no material regression in unsupported facts or escalation precision;
- reproducible adapter loading and rollback to the untuned adapter;
- latency and memory within the frozen local/deployment budget.

If the tuned model fails the gate, retain the experiment and model card as an
honest no-go result. Do not redefine success post hoc.

## Explicit non-goals

- DPO, GRPO, RL, RLAIF, voice, or production serving;
- training Slow or transferring model authority into Fast;
- PostgreSQL, Temporal, channels, UI, deployment, or release;
- regenerating or overwriting Phase 03A1 r2/r3/r4/r5 evidence;
- broad evaluation-matrix expansion before the same-model comparison is valid;
- credentials, consumer PII, real Provider data, or unbounded teacher spend.

## Required fresh-session output

The next session should stop after producing a reviewed Phase 03B readiness
decision and executable bounded contract. It must report one of:

- `READY_FOR_QLORA_SMOKE` with frozen inputs, budget, acceptance criteria, and
  verification plan;
- `NEEDS_BOUNDED_REMEDIATION` with the smallest data/evaluator work required;
- `NOT_READY` with evidence and no training action.

Training begins only if the user explicitly approves the resulting bounded
contract and any required model download, compute, or external cost.
