# Harness Context

Store only small, phase-specific evidence that helps an implementation or review agent execute a prepared phase without rediscovering the same facts.

Each context file must identify:

- the phase and question it supports;
- source files or official external sources;
- what is observed, inferred, proposed, or still unverified;
- the date when drift-prone information was checked.

Do not copy the PRD, architecture document, source code, hidden chain-of-thought, secrets, PII, large generated output, or model datasets into this directory. Durable product decisions belong in `docs/decisions/`; domain language belongs in `CONTEXT.md`; execution evidence belongs in `harness/log/` (historical entries in `harness/build-log.md`).

Context files, newest first. Each was written for the named phase's
activation and is historical once that phase is complete; it is retained for
audit and as the observed baseline the next phase built on.

- `phase-06b-controlled-channels-preflight.md`: Phase 06B proposal/preflight audit on `40e324f` (`GO_FOR_PHASE_PROPOSAL`); Phase 06B1 was executed from it, Phase 06B2 remains unauthorized.
- `phase-06a-preflight.md`: observed post-05A Web/Runtime baseline, recovery wire seam, browser command ownership, and monotonic-state rules.
- `phase-05a-preflight.md`: observed post-04D Runtime/PostgreSQL baseline, Temporal SDK semantics, inward Runtime seam, command idempotency, and fault-injection boundary.
- `phase-04d-preflight.md`: Phase 04D preflight audit on `e64fa85` (`GO`).
- `phase-04c-preflight.md`: activation-time observations and frozen decisions for the PostgreSQL Case store.
- `phase-local-conversation-intake-preflight.md`: activation baseline and user gate for the four-fact intake UX after the PR #18 closeout.
- `phase-minimal-local-web-demo-preflight.md`: activation through post-merge closeout evidence for the bounded Web demo.
- `phase-04b-preflight.md`: activation-time observations and frozen decisions for the model-backed adapter.
- `phase-04a-preflight.md`: activation-time observations for the Thin Agent Runtime after PR #11.
- `phase-03b-readiness-preflight.md`: Phase 03B Gate 0 readiness evidence separated from Sol's frozen decisions.
- `phase-03a1-evaluation-validity-smoke-preflight.md`, `phase-03a1-hosted-rerun-preflight.md`, `phase-03a1-evaluation-erratum-preflight.md`, `phase-03a1-baselines-preflight.md`: the Phase 03A1 evaluation sub-gates.
- `phase-03a1-preflight.md`: observed post-03A0 implementation surface, frozen Harness seams, and excluded model/training work.
- `phase-03a0-preflight.md`: observed post-02 architecture gaps and frozen Fast/Slow/shared-state decisions.
- `phase-02-preflight.md`: observed post-01B baseline and the normalized trajectory/Data Factory seam.
- `phase-01b-preflight.md`: observed post-01A baseline and the simulator benchmark seam.
- `phase-01a-preflight.md`: observed post-contract baseline and the deterministic Provider-loop seam.
- `phase-00b-preflight.md`: observed contract-package baseline and the six pre-implementation decisions.

Phase 07A had no separate preflight file; its baseline is recorded in the
contract `harness/build/phase-07a-reproducible-local-portfolio-demo.md`.
