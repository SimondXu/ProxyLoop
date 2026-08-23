# Phase 02 Preflight

Date: 2026-08-23

## Starting Point

- `main` commit: `0d05ab2`
- active branch: `feat/phase-02-data-factory`
- Phase 01B: independently reviewed, CI-validated, and squash merged through PR #5
- worktree at activation: only root-local Phase 02 planning files were untracked

## Reusable Surface

- 16 immutable Scenario Families and two Provider configurations producing 32 scenarios;
- stable 10/3/3 family and 20/6/6 scenario split manifest with a content fingerprint;
- allowlisted Safe Observation and a scripted consumer that receives no private scenario state;
- deterministic Provider environment and environment-owned verification result;
- Phase 01B benchmark composition and forbidden observation-key vocabulary;
- repository-native Ruff, mypy, pytest, contract-drift, TypeScript, layout, lock, compile, and Compose checks.

## Demonstrated Gaps

- `ml/data_pipeline` contains no package, independent project lock, schema, runner, curation checks, or tests;
- no normalized trajectory record or training-content fingerprint;
- no source/license/lineage/PII/deduplication/cross-split leakage/rejection gate;
- no 100–200 record pilot, cost/quality report, annotation guide, or review sample.

## Frozen Decisions

- Phase 02 validates a one-turn normalized trajectory interface; multi-turn learned-model rollouts are deferred;
- 32 scenarios times four deterministic response variants yield 128 accepted records;
- eight deliberately invalid probes exercise quarantine without entering the accepted manifest;
- all derivatives inherit, rather than recompute, the Phase 01B split assignment;
- exact content deduplication ignores identity/curation metadata; semantic fingerprints are a hard cross-split check only;
- only small redacted schemas, manifests, reports, and samples are committed;
- no external teacher/provider/judge model is called, and external token/cost totals remain exactly zero;
- the automated pilot can validate the Data Factory but cannot set `training_ready=true` or claim completed human review.

## Risks to Verify

- four response variants represent real content differences rather than ID-only duplication;
- source/license metadata is a hard acceptance gate rather than optional reporting;
- private scenario/evaluator fields cannot reach model-facing payloads;
- rejection probes cannot contaminate accepted manifests or aggregate quality claims;
- independent `ml/` dependencies do not make runtime import ML code or pull training/serving packages into Phase 02.
