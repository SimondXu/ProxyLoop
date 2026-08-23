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
