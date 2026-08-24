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
| 03A0 | Fast/Slow architecture and acceptance criteria | Complete; squash merged as `54afcb8` through PR #7 | `harness/build/phase-03a0-fast-slow-architecture.md` |
| 03A1-H | Deterministic multi-turn evaluation harness | Complete; squash merged as `e08c9b6` through PR #8 | `harness/build/phase-03a1-harness.md` |
| 03A1-B | Untuned Qwen/Terra baselines | Complete; full gate passed through PR #9 | `harness/build/phase-03a1-baselines.md` |
| 03A1-E | Evaluation erratum and leakage-safe second run | Complete; terminal Provider blocker; PR #10 gates passed | `harness/build/phase-03a1-evaluation-erratum.md` |
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

> Phase 03A0 remains complete at `54afcb8`.
>
> Phase 03A1-H is squash merged as `e08c9b6` through PR #8. Phase 03A1-B completed its frozen model matrix, independent review, and PR #9 gates.

Phase 03A1-E completed its bounded gate with an honest terminal Provider blocker. The
immutable r2 evidence records one unknown-cost hosted failure and a global
zero-call abort; the source-bound r3 report corrects attribution offline with
zero new external dispatches. PR #10 passed phase-gate and GitGuardian. Phase
03A1-E cannot train, expand training data, or activate Phase 03B. Teacher-backed
expansion, serving, product Agent, channels, and UI remain inactive.
