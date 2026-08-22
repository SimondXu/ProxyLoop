# ProxyLoop Execution Plan

This is the harness-level phase index. Detailed product requirements live in the specification, and executable acceptance criteria live in the selected `harness/build/phase-*.md` file.

## Status

| Phase | Outcome | Status | Gate artifact |
|---|---|---|---|
| 00A | Repository foundation and documentation | Complete | Initial repository setup and layout validation |
| 00B | Canonical contracts and contract verification | In progress | `harness/build/phase-00b-contracts.md` |
| 01 | Fictional provider simulator and benchmark | Not started | To be prepared after 00B approval and completion |
| 02 | Data factory and trajectory pilot | Not started | To be prepared after Phase 01 |
| 03 | Baselines, SFT, and evaluation | Not started | To be prepared after Phase 02 |
| 04 | Serving and control plane | Not started | To be prepared after Phase 03 |
| 05 | Durable agent loop | Not started | To be prepared after Phase 04 |
| 06 | Controlled channels and UI | Not started | To be prepared after Phase 05 |
| 07 | Portfolio hardening | Not started | To be prepared after Phase 06 |

## Critical Dependency Chain

```text
domain contracts
  -> simulator and deterministic verifier
  -> trajectory schema and data quality
  -> model baselines and post-training
  -> serving and business control plane
  -> Temporal durability and approvals
  -> controlled email/voice and UI
  -> reproducible portfolio evidence
```

The web UI is not the first implementation phase. A disposable visual prototype may be created later to explore user experience, but production UI work waits for stable case, approval, offer, evidence, and completion contracts.

## Parallelization Policy

Phase 00B is intentionally narrow and mostly sequential because every downstream area depends on the same canonical contracts.

After contracts stabilize, these workstreams can run in parallel when the user explicitly requests delegation:

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

Active phase objective:

> Complete Phase 00B exactly as specified in `harness/build/phase-00b-contracts.md`, record verification evidence, obtain an independent review, and stop at the phase gate without starting the simulator.
