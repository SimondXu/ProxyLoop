# Phase 01B Preflight

Date: 2026-08-23

## Starting Point

- `main` commit: `c6e7b33`
- active branch: `feat/phase-01b-simulator-benchmark`
- Phase 01A: independently reviewed and squash merged as `f7f3cf7`
- worktree at activation: only root-local planning files were untracked

## Reusable Surface

- canonical Case, goal, constraint, bill, offer, action, approval, Evidence, and Completion Decision contracts;
- Phase 01A's deterministic Provider-held confirmation authority;
- exact approval binding and completion verification in `telecom_domain`;
- repository-native Ruff, mypy, pytest, contract-drift, layout, lock, compile, and Compose checks.

## Demonstrated Gaps

- one hard-coded Provider configuration and success episode only;
- no Safe Observation Adapter or `agent_core` package;
- no versioned scenario families, family/entity split, second Provider configuration, scripted oracle, ceiling report, leakage scan, or benchmark CLI.

## Frozen Decisions

- 16 families and 2 Provider configurations yield 32 deterministic scenarios;
- one fixture-driven engine, not one class per family;
- safe observation and oracle input live in `agent_core` and depend only on canonical contracts;
- environment definitions and deterministic verification remain in `provider_simulator`;
- benchmark labels and gold/private fields never enter the serialized observation;
- the gate requires 32 valid scripted outcomes, zero false completions, and zero leakage violations;
- Phase 02 trajectory/data-factory work and all model/product layers remain excluded.

## Risks to Verify

- split grouping remains stable under reordered input;
- the oracle cannot reach hidden scenario or Provider configuration state;
- invalid scenarios prove safe refusal/replan/escalation, not forced completion;
- Phase 01A compatibility and inward dependency boundaries remain intact.
