# Findings and Decisions

## Requirements

- Produce a complete, build-ready plan for a Pine-like project.
- Include product scope, ML lifecycle, data lifecycle, system architecture, technical stack, repository strategy, milestones, evaluation, deployment, monitoring, risks, and open questions.
- Optimize for a strong AI/ML-agent portfolio project rather than a toy demo or unsupported production claim.
- Train one Qwen3-4B Fast Response Model; use a hosted frontier model as the Slow Reasoner.
- Preserve a path to durable loops, email, and controlled voice without forcing them into the first training milestone.

## Consolidated Findings

- Pine publicly presents itself as a consumer completion agent for bill reduction, cancellation, refunds/complaints, travel help, appointments, calls, emails, web actions, and follow-ups.
- The most suitable first vertical is mobile bill optimization against a fictional provider, not a real T-Mobile integration. The first case optimizes one selected postpaid line; home internet remains a later service-type adapter.
- The first supported provider actions should be limited to plan change, optional add-on removal, and a predefined retention credit/promotion.
- tau2 Telecom is useful for schemas, account/billing concepts, user/provider dialogue patterns, and simulator mechanics, but it is a provider-side customer-service environment rather than a ready-made consumer negotiation benchmark.
- Pine's released tau2 voice trajectories cover the same public tasks and therefore cannot be both training data and an uncontaminated headline test set.
- A custom simulator, safe observation adapter, consumer-specific verifier, family-safe split, provider ensemble, and leakage scanner are required.
- Training data volume must be justified by learning curves over independent scenario families, not by raw trajectory count.
- The Fast Model must learn local policy fields plus response generation. It must not own final completion, business state, credentials, or high-risk side effects.
- The Slow Reasoner should return versioned structured strategy packets, not raw chain-of-thought.
- Temporal, Gmail, and LiveKit are later integration milestones; they are not prerequisites for the text research MVP.
- The current `uv` workspace model gives multiple Python packages a shared lockfile and root command surface, which matches the proposed Python-first monorepo; all members must share a compatible Python version range.
- LiveKit's official outbound flow creates a SIP participant through an outbound trunk and connects it to an agent room. It should remain a channel adapter and must not own case/workflow state.
- Temporal's documented value is durable resumption across crashes and long waits. That supports the later cross-day loop but does not remove the need for application-level idempotency on external side effects.
- Pydantic Evals can serialize typed datasets/evaluators with JSON Schema, but project-owned deterministic evaluators remain necessary for business and safety outcomes.

## Technical Decisions

The decisions originally tabulated here (monorepo, `uv`/`pnpm`, Makefile plus
Compose, Python-first core, generated frontend types, Qwen3-4B Fast
checkpoint, 24GB QLoRA target, `gpt-5.6-terra` Slow Reasoner, MLflow OSS,
vLLM, immutable manifests) are recorded once, with rationale and status, in
the dated ADRs:

- [`docs/decisions/2026-08-21-monorepo.md`](../decisions/2026-08-21-monorepo.md)
- [`docs/decisions/2026-08-22-implementation-defaults.md`](../decisions/2026-08-22-implementation-defaults.md)

Those files are authoritative; this document keeps only the research findings
and resources that fed them.

## Issues Encountered

| Issue | Resolution |
|---|---|
| Earlier documents disagreed on car lease, Retail, and telecom | Treat telecom as the recommended first vertical and document Retail only as a safer benchmark fallback. |
| tau2 can expose task answers and provider internals through environment info | Require a safe observation adapter that strips provider policy, DB, evaluation criteria, reference actions, and rewards. |
| Official benchmark splits and public trajectories can leak families/entities | Create project-owned splits before data generation and quarantine contaminated sources from headline evaluation. |

## Resources

- Pine official capability page: https://www.19pine.ai/ai-information-page/
- Pine bill negotiation: https://www.19pine.ai/blog/pine-bill-negotiation
- Pine released voice trajectories: https://huggingface.co/datasets/pine-ai/pine-realtime-1.0-preview-tau2-voice-trajectories
- tau2 official repository: https://github.com/sierra-research/tau2-bench
- tau2 Gym interface: https://github.com/sierra-research/tau2-bench/blob/main/src/tau2/gym/README.md
- Temporal Python SDK: https://github.com/temporalio/sdk-python
- PydanticAI: https://github.com/pydantic/pydantic-ai
- LiveKit Agents: https://github.com/livekit/agents
- uv workspaces: https://docs.astral.sh/uv/concepts/projects/workspaces/
- pnpm: https://pnpm.io/
- Temporal documentation: https://docs.temporal.io/
- LiveKit outbound calls: https://docs.livekit.io/telephony/making-calls/outbound-calls/
- Pydantic Evals dataset serialization: https://ai.pydantic.dev/evals/how-to/dataset-serialization/
- Qwen3-4B-Instruct-2507 model card: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- OpenAI model catalog: https://developers.openai.com/api/docs/models
- MLflow tracking server: https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/
- vLLM structured outputs: https://docs.vllm.ai/en/latest/features/structured_outputs/
