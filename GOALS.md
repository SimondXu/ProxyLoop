# ProxyLoop Goals

## Product Outcome

Build a portfolio-grade consumer negotiation and task-completion agent that can operate inside explicitly delegated limits, survive waits and retries, and claim completion only when external evidence satisfies deterministic checks.

The first vertical is fictional-provider, mobile-postpaid telecom bill optimization. The repository must demonstrate a credible path from typed contracts and simulator evaluation through model post-training, serving, a durable workflow, and controlled channels without pretending to automate real providers in the research MVP.

## Success Conditions

- Domain, authorization, evidence, and completion concepts are represented by versioned typed contracts.
- A fictional provider simulator supports reproducible, leakage-safe evaluation.
- Fast Model candidates are selected from local benchmark evidence, not vendor claims alone.
- Slow reasoning and Fast turn policy have explicit, replaceable interfaces.
- Consequential side effects require deterministic policy checks and version-bound approval.
- Durable retries, waits, duplicate callbacks, and worker restarts do not duplicate consequential actions.
- Reported results distinguish measured evidence from proposed architecture and unverified external claims.
- A reviewer can reproduce the simulator benchmark and understand system limitations.

## Scope

Included in the staged roadmap:

- one postpaid mobile-line telecom vertical using fictional providers;
- Qwen3-4B as the Fast Model default candidate;
- LFM2.5-2.6B and smaller/larger Qwen checkpoints as benchmark challengers where defined;
- hosted Slow Reasoner behind a typed adapter;
- simulator, data factory, SFT/QLoRA, evaluation, serving, control plane, durable workflow, and controlled demo channels;
- a later approval/timeline UI after the core contracts, simulator, and evaluation path exist.

## Non-Goals

- real-carrier autonomous negotiation in the research MVP;
- automatic purchase, payment, credit application, contract acceptance, or account cancellation;
- medical, legal, financial-dispute, or other high-risk verticals;
- multiple consumer verticals before telecom gates pass;
- production-scale reliability or a production-grade Pine clone claim;
- GRPO before simulator, verifier, data, and SFT gates justify it;
- frontend-first development that invents unstable backend contracts.

## Constraints

- Local development target: the user's Apple Silicon workstation.
- Training target: reproducible local smoke work plus a bounded 24 GB CUDA QLoRA path when required.
- Runtime environments remain isolated: web, Python runtime, ML, and voice do not share one dependency lock.
- No secrets or consumer PII are committed.
- No fixed performance, cost, or completion claims are published before measurement.

## Authoritative Detail

- Product and ML requirements: `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`
- System boundaries: `docs/architecture.md`
- Frozen implementation defaults: `docs/decisions/2026-08-22-implementation-defaults.md`
- Execution order and current gate: `PLANS.md`
