# ProxyLoop Execution Plan

This is the harness-level phase index. Detailed product requirements live in the specification, and executable acceptance criteria live in the selected `harness/build/phase-*.md` file.

## Status

| Phase | Outcome | Status | Gate artifact |
|---|---|---|---|
| 00A | Repository foundation and documentation | Complete | Initial repository setup and layout validation |
| 00B | Canonical contracts and contract verification | Complete | `harness/build/phase-00b-contracts.md` |
| 01A | Thin deterministic Provider loop | Complete | `harness/build/phase-01a-provider-simulator.md` |
| 01B | Simulator breadth and benchmark gate | Complete | `harness/build/phase-01b-simulator-benchmark.md` |
| 02 | Data factory and trajectory pilot | Complete; squash merged as `f45b1ea` through PR #6 | `harness/build/phase-02-data-factory.md` |
| 03A0 | Fast/Slow architecture and acceptance criteria | Local gate approved; PR, CI, and merge pending | `harness/build/phase-03a0-fast-slow-architecture.md` |
| 03A1 | Multi-turn evaluation harness and untuned baselines | Not started | Prepared only after Phase 03A0 merge and a new user gate |
| 03B | Open-data SFT, gap-driven project data, and evaluation | Not started | Decided from Phase 03A1 failure slices |
| 04 | Serving and control plane | Not started | To be prepared after Phase 03 |
| 05 | Durable agent loop | Not started | To be prepared after Phase 04 |
| 06 | Controlled channels and UI | Not started | To be prepared after Phase 05 |
| 07 | Portfolio hardening | Not started | To be prepared after Phase 06 |

## Critical Dependency Chain

```text
domain contracts
  -> simulator and deterministic verifier
  -> trajectory schema and data quality
  -> Fast/Slow routing and shared-state contract
  -> multi-turn evaluation harness and untuned baselines
  -> evidence-driven public/project data and post-training
  -> serving and business control plane
  -> Temporal durability and approvals
  -> controlled email/voice and UI
  -> reproducible portfolio evidence
```

The web UI is not the first implementation phase. A disposable visual prototype may be created later to explore user experience, but production UI work waits for stable case, approval, offer, evidence, and completion contracts.

## Parallelization Policy

Phase 00B is intentionally narrow and mostly sequential because every downstream area depends on the same canonical contracts.

After contracts stabilize, Sol may run these workstreams in parallel when their ownership is independent and delegation materially improves execution:

- simulator transition engine and scenario authoring;
- deterministic verifier and adversarial test fixtures;
- benchmark/reporting infrastructure;
- read-only architecture or documentation review.

These remain sequential or require an integration gate:

- canonical contract changes before generated schemas and TypeScript types;
- simulator semantics before large-scale data generation;
- dataset gates before full training;
- model evaluation before serving promotion;
- policy/approval semantics before durable side effects;
- stable product contracts before production UI and channels.

## Goal Usage

Create one Codex Goal only for the single approved phase. The Goal should quote the phase objective and acceptance criteria, and should be marked complete only after evidence and independent review are recorded. Do not create a permanent “finish the whole repository” Goal or use a loop to bypass human gates.

Current gate:

> Phase 02 is squash merged as `f45b1ea`; its redacted review sample remains `pending_human` and `training_ready=false`. The user explicitly activated Phase 03A0 to freeze Fast/Slow routing, model-external Case context, authority ownership, stale-result handling, Qwen training boundaries, and Phase 03A1 acceptance criteria.

Phase 03A0 does not implement or call a model. Phase 03A1 evaluation implementation and all model downloads/calls, teacher-backed expansion, training, serving, product Agent, channels, and UI remain inactive and require new explicit user gates.
