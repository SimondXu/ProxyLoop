# Task Plan: Pine-like Telecom Agent Blueprint

## Goal

Create a build-ready plan for a portfolio-grade Pine-like Consumer Telecom Bill Optimization Agent, including product scope, ML lifecycle, system architecture, monorepo structure, delivery phases, validation gates, risks, and unresolved decisions.

## Current Phase

Complete

## Phases

### Phase 1: Requirements and Evidence Consolidation

- [x] Reconcile the earlier car-lease, retail, and telecom proposals.
- [x] Freeze the recommended first vertical at the planning level.
- [x] Capture verified Pine, tau2, data, workflow, and voice constraints.
- **Status:** complete

### Phase 2: Architecture and Repository Design

- [x] Define product, ML, data, serving, workflow, and channel boundaries.
- [x] Decide monorepo organization and root toolchain.
- [x] Define canonical contracts and sources of truth.
- **Status:** complete

### Phase 3: Build Roadmap and Validation Gates

- [x] Break delivery into research MVP, integrated demo, and optional extensions.
- [x] Define measurable entry and exit gates for every phase.
- [x] Estimate time, cost drivers, and dependencies.
- **Status:** complete

### Phase 4: Documentation Delivery

- [x] Write the product/engineering specification.
- [x] Write the architecture overview.
- [x] Record the monorepo decision.
- [x] Review documents for contradictions, unsupported claims, and missing scope.
- **Status:** complete

### Phase 5: Implementation Defaults and Model Update

- [x] Verify current official facts for Qwen3-4B, the hosted Slow provider, experiment tracking, and serving runtime.
- [x] Replace the provisional 7B-class Fast Model with Qwen3-4B and freeze the first account type.
- [x] Select one experiment registry and one production GPU serving runtime.
- [x] Update the GitHub-facing project identity and validate document consistency.
- **Status:** complete

## Key Questions

1. What is the exact first use case and what is explicitly excluded?
2. Which model is trained, which model remains a hosted frontier model, and how do they coordinate?
3. How is training/evaluation data generated without oracle leakage or benchmark contamination?
4. Which component owns business truth, workflow truth, model state, and external side effects?
5. What is the smallest scope that still demonstrates a credible end-to-end ML lifecycle and durable AI agent?
6. Which repository layout minimizes cross-language friction without creating premature platform infrastructure?

## Decisions Made

| Decision | Rationale |
|---|---|
| First vertical: fictional-provider Consumer Telecom Bill Optimization | Best balance of Pine similarity, Fast/Slow value, measurable outcomes, and custom-data lifecycle; avoids real T-Mobile credentials/compliance in the first version. |
| Train one Fast Response Model; use a hosted frontier Slow Reasoner | Keeps training scope credible while preserving strategic reasoning quality and a clear latency/cost hypothesis. |
| Product and ML work live in one monorepo but remain separate modules | Contracts, simulator, evaluation, and product integration evolve together; separation prevents the workflow product from becoming training code. |
| Build a custom family-safe telecom benchmark before teacher generation | Prevents tau2/Pine contamination and supports defensible held-out evaluation. |
| PostgreSQL is authoritative for business facts; Temporal owns workflow control | Avoids competing sources of truth between database, workflow history, and LLM context. |
| Public identity: `ProxyLoop` / `ProxyLoop-A-Durable-Consumer-Negotiation-Task-Completion-Agent` | Describes the durable consumer-task platform without using Pine or a real carrier trademark in the project name. |
| Mobile-first, one selected postpaid line | Reuses the strongest telecom schema/task seeds while bounding multi-line pricing and device-financing complexity. |
| Fast Model: `Qwen/Qwen3-4B-Instruct-2507` | A non-thinking 4B checkpoint keeps the Fast path and QLoRA target practical; promotion still requires the project smoke benchmark. |
| Slow Model: OpenAI `gpt-5.6-terra` | Current balanced reasoning tier with structured outputs; kept behind a provider-neutral contract. |
| MLflow OSS and vLLM | One self-hostable lifecycle tracker and one promoted Linux/CUDA inference runtime keep the first implementation reproducible and focused. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `git status` failed because the directory is not a Git repository | 1 | Treat the directory as a new project; do not initialize Git without explicit user authorization. |

## Notes

- This planning pass creates documentation only. It does not initialize Git, scaffold services, download models, or contact external providers.
- The selected public identity is `ProxyLoop`; it intentionally does not use Pine or a real carrier trademark.
