# Freeze the Initial Product, Model, and ML Platform Defaults

## Status

Accepted for the first implementation spike. Model promotion remains conditional on measured gates.

## Decision

| Concern | Initial choice | Reconsider only when |
|---|---|---|
| Public identity | Product `ProxyLoop`; repository `ProxyLoop-A-Durable-Consumer-Negotiation-Task-Completion-Agent` | A verified naming or legal conflict appears. |
| First service | One selected postpaid mobile line per case | Mobile benchmark and ML gates pass; then add home internet through `service_type`. |
| Fast checkpoint | `Qwen/Qwen3-4B-Instruct-2507` | The smoke benchmark fails policy, structured-output, latency, license, or LoRA reproducibility gates. |
| Fast behavior | Non-thinking, bounded structured decision plus concise response | A measured ablation shows another output contract is safer or more accurate. |
| Phase 03A1 Fast side effects | `FastTurnDecision.action_intent=null` | A later explicit contract/evaluation gate proves a bounded Fast-originated intent is useful and safe. |
| Routing | Deterministic reason-coded Router over a version-pinned Case Context Snapshot | Measured evidence justifies a different policy without moving authority into a model. |
| Shared model context | Separate allowlisted Fast/Slow views derived from model-external Case state | A contract/evaluation gate proves another projection preserves state and leakage invariants. |
| Training hardware | One 24GB CUDA GPU, 4-bit QLoRA, initial 8K sequence cap | OOM or throughput measurements justify one 48GB GPU. |
| Local ML smoke path | MLX-LM on the Apple M4 Pro | It cannot reproduce the required adapter or evaluation behavior. |
| Slow Reasoner | OpenAI `gpt-5.6-terra`, structured output, initial medium reasoning effort | Cost/quality evaluation or account availability fails; swap through the provider adapter. |
| Experiment system | MLflow OSS | A real multi-user requirement justifies hosted W&B migration. |
| Promoted Fast serving | vLLM on Linux/CUDA | It fails frozen Qwen structured-output, latency, stability, or memory gates. |

## Why These Defaults

- Mobile has the strongest immediately reusable public telecom schema and task vocabulary while remaining close to the intended consumer-advocacy scenario. Limiting each case to one selected line prevents multi-line pricing and device financing from dominating the first benchmark.
- The chosen Qwen checkpoint is a 4B, Apache-2.0, non-thinking-only instruct model. That removes hidden reasoning latency from the Fast path and is materially more practical for QLoRA and demo serving than a 7B-class model.
- A 24GB GPU is a cost-controlled first target, not a guarantee. Context is deliberately bounded because the Fast Model receives structured state, the current strategy packet, and a recent-turn window instead of the entire case history.
- Fast and Slow never share hidden model memory or call one another. The deterministic Router projects separate views from one immutable Case snapshot, rejects stale results, and serializes Case writes and side effects.
- Qwen is trained for bounded turn policy, candidate fact extraction, reasoner requests, completion candidates, and concise response only. Strategy, tool planning/execution, approval, memory, Evidence verification, and final completion remain outside its target.
- `gpt-5.6-terra` is the initial Slow model because current OpenAI documentation positions it as the intelligence/cost balance and documents structured outputs and function calling. The domain contract, not the vendor payload, remains authoritative.
- MLflow covers local experiment tracking and a self-hostable registry without making a hosted account part of reproducibility.
- vLLM is directly documented by Qwen for this checkpoint and provides OpenAI-compatible structured outputs. SGLang remains a contingency, not a second maintained path.

## Evidence Boundary

These are implementation defaults, not measured project results. Before promotion, the project must publish the base checkpoint's JSON validity, policy metrics, false-completion rate, unsupported-fact rate, latency, memory use, and QLoRA reproducibility on the project-owned smoke set.

Official references:

- https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- https://developers.openai.com/api/docs/models/gpt-5.6-terra
- https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/
- https://docs.vllm.ai/en/latest/features/structured_outputs/

## Amendment 2026-09-21 — Fast checkpoint moved to Qwen3-8B

The user redirected the Fast checkpoint from `Qwen/Qwen3-4B-Instruct-2507`
to **`Qwen/Qwen3-8B`** for the Phase 03C redo. Facts recorded at the time of
the decision:

- Hugging Face lists no `Qwen3-8B-Instruct-2507`; `Qwen/Qwen3-8B` is the
  hybrid thinking/non-thinking model, so non-thinking mode must be forced
  with `enable_thinking=False` at training and inference and `<think>`
  output is an evaluator failure. The original 4B rationale ("non-thinking-only
  removes hidden reasoning latency") no longer applies automatically.
- Training hardware default changes from "one 24GB CUDA GPU, 4-bit QLoRA" to
  one 80 GB-class GPU with bf16 LoRA; a 24 GB card would require 4-bit QLoRA
  on 8B and reintroduce the quantised-base mismatch with bf16 vLLM serving.
- Serving memory and latency roughly double versus 4B; the promoted-serving
  gates in this document apply unchanged.
- This is a checkpoint choice, not a measured result. The Phase 03B `NO_GO`
  was caused by prompt, parser, data, and scale problems, not by model size
  (`docs/research/2026-09-21-phase-03b-post-training-review.md`).

The rows above are retained as the 2026-08-22 defaults; where they conflict
with this amendment, the amendment wins.
