# ML evidence

What the project's evaluation and post-training work does and does not show.
Every number links to a committed artifact; nothing here is a projection.

## The setup

The agent splits each turn between a **Fast** model (a small model the
project intends to own — `Qwen/Qwen3-4B-Instruct-2507` for the results below,
redirected to `Qwen/Qwen3-8B` on 2026-09-21 for the prepared redo) and a
**Slow** reasoner (hosted). Both return typed JSON (`FastModelOutput`,
`SlowWorkResult`) that deterministic code checks against Case state before
anything happens. Because the outputs are structured decisions, they can be
scored exactly against a scripted oracle and a verifier that inspects the
simulated provider's real state — no LLM judge is involved in the headline
numbers.

The simulator provides 16 scenario families × 2 provider configurations. The
scripted oracle completes all 32 with zero false completions and zero
private-field leakage; that is the environment ceiling
(`data/manifests/phase-01b-ceiling-report.json`,
`data/manifests/phase-03a1-ceiling-report.json`).

## Results so far

| Run | What it measured | Result | Artifact |
|---|---|---|---|
| Phase 03A1-B (r1) | untuned Qwen Fast + hosted Slow, first full matrix | superseded by the erratum below | `data/evaluation/phase-03a1-baselines-report.json` |
| Phase 03A1-E (r2/r3) | leakage-safe rerun; one hosted failure of unknown cost recorded, attribution corrected offline | untuned Qwen: 32/32 schema-valid JSON on the schema-embedding prompt | `phase-03a1-r2-*`, `phase-03a1-r3-*` |
| Phase 03A1-R (r4) | full hosted matrix after fixing the Slow output union (`oneOf` → `anyOf`) | evidence complete; hosted E2E low (best condition 3/32) | `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` |
| Phase 03A1-V (r5) | six-episode diagnostic of why r4 was implausibly low | 0/6 → **5/6** E2E after giving model and oracle the same public inputs; the last case is an evaluation-contract mismatch (a 12-month fee predicate the model could not see); USD 0.117 hosted spend | `data/evaluation/phase-03a1-r5-validity-smoke-report.json` |
| Phase 03B | one 40-iteration QLoRA smoke on 20 examples, 6-scenario A/B | A 1/6, B 0/6 schema-valid; decision **`NO_GO_STOP_PHASE03B`** | `data/experiments/phase-03b-qlora-smoke/results/comparison.md` |

## What these results mean

- **The evaluation harness works and found its own bug.** r4's low hosted
  numbers were traced to the model and the oracle seeing different inputs;
  after parity the same model went to 5/6. The remaining miss exposed a
  predicate the oracle enforced but the consumer goal never stated. Both are
  recorded as erratum artifacts, not overwritten.
- **Untuned Qwen3-4B produces valid structured output when the prompt embeds
  the schema** (32/32 in r2/r4). Format is not the model's bottleneck.
- **The Phase 03B smoke does not tell us whether fine-tuning helps.** A
  post-hoc review (`docs/research/2026-09-21-phase-03b-post-training-review.md`)
  found that the 03B prompt dropped the schema and broke the untuned
  baseline (its 6 "invalid" outputs are all valid JSON with an over-long
  `reason_code`), that the tuned arm's 6 "invalid JSON" outputs are all
  markdown-fenced JSON the parser refused to strip, and that 20 examples, 6
  distinct targets and 10 optimizer updates at LR 1e-5 do not constitute a
  training run. The `NO_GO` stands as a decision to stop *that* experiment;
  it is not evidence about the model or about QLoRA.
- **Training on a Mac was a symptom, not the cause.** The MLX run was sound
  as a smoke; the problems were prompt, parser, data, and scale, and would
  have reproduced on any GPU.

## What would count as evidence

The review proposes a bounded redo: verifier-filtered teacher distillation
(teacher decisions must agree with the oracle to be kept), a parameterised
scenario generator so examples differ in numbers and constraints, official
bf16 weights with LoRA on one cloud GPU via TRL/PEFT, checkpoint selection by
the real evaluator, and held-out families with n ≥ 100 per arm. Its
pre-registered Go/No-Go includes the outcome "prompt plus constrained
decoding is enough, no distillation needed" as a legitimate result. None of
this is authorized yet; see `harness/status.toml`.
