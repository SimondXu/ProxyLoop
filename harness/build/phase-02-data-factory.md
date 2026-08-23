# Phase 02 — Data Factory and Trajectory Pilot

**Status**: Implementation and independent local gate approved; PR CI, GitGuardian, and squash merge pending.

**Activation**: Explicitly approved by the user on 2026-08-23 after Phase 01B was squash merged as `0d05ab2`. Active branch: `feat/phase-02-data-factory`.

**Roadmap source**: Phase 2 in `docs/specs/2026-08-21-telecom-bill-optimization-agent.md`

## Objective

Prove that Phase 01B's leakage-safe fictional-Provider episodes can be converted into reproducible, normalized, auditable trajectory candidates before any model is selected, called, trained, or evaluated.

This phase establishes the Data Factory seam and a bounded pilot. It does not claim that the deterministic pilot is training-ready.

## In Scope

- a versioned normalized trajectory schema under `data/schemas/`;
- an independent `ml/` uv project and `proxyloop_data_pipeline` module;
- a deterministic rollout/export runner that composes Phase 01B Safe Observation, scripted-consumer, Provider environment, verifier, and split interfaces;
- exact source, license, lineage, generator, simulator, prompt/config, verification, review, rejection, and content-fingerprint metadata;
- deterministic PII, forbidden-field, exact-deduplication, semantic cross-split leakage, split-inheritance, and rejection checks;
- 136 deterministic candidates: 128 accepted pilot trajectories from 32 scenarios and four response variants, plus eight quarantined negative probes covering the rejection interface;
- committed small artifacts only: schema, accepted manifest, quarantine manifest, cost/quality report, redacted review sample, and annotation guide;
- repository-native format, lint, type, test, artifact-drift, layout, runtime lock, ML lock, pnpm lock, compile, and Compose checks.

## Frozen Trajectory Contract

- `schema_version="1.0"` identifies the normalized record semantics.
- A Phase 02 trajectory is one Provider turn followed by one structured consumer decision, one deterministic response text, and one environment-owned verification. Multi-turn teacher/model episodes remain future work.
- Every derivative inherits its `family_id`, `entity_cluster`, Provider configuration, and split from the committed Phase 01B split manifest. The Data Factory does not recompute or reassign splits.
- The project-owned synthetic source uses an explicit `LicenseRef-ProxyLoop-Synthetic-1.0` record with approved training-research use. Missing or non-approved license status is rejected.
- Generator snapshots identify the scripted oracle, deterministic Provider configuration, and deterministic verifier. No field implies that an external teacher, Provider model, or judge was called.
- A trajectory content hash binds the model-facing observation, structured decision, response text, and verification. Identity and curation metadata cannot make duplicate learning content appear unique.
- Exact duplicate learning content is quarantined. A frozen deterministic lexical fingerprint removes opaque case, offer, and timestamp identifiers, then Unicode-normalizes, case-folds, whitespace-collapses, and punctuation-normalizes the remaining public observation, structured action, completion flag, and response text. It is a hard cross-split leakage heuristic; it is not embedding similarity or proof of semantic equivalence. Related variants inside one inherited split remain allowed and retain their common derivation parent.
- The model-facing payload cannot contain scenario labels, split assignments, Provider-private policy, expected actions/outcomes, reference actions, rewards, verifier criteria, database/account state, or private reason codes.
- Deterministic PII scanning covers explicit high-risk patterns and fields, but is not represented as a substitute for human semantic review. Accepted pilot records must have zero detected PII; the review sample remains `pending_human`.
- The 128 accepted records validate the factory and artifact gate only. The report must set `training_ready=false` and may recommend only conditional Data Factory expansion, not Phase 03 training.

## Package Boundaries

```text
proxyloop_data_pipeline -> proxyloop_agent_core + proxyloop_provider_simulator
runtime packages/services -/-> ml
training/evaluation/serving -/-> Phase 02 data pipeline execution
```

The Data Factory owns normalization, lineage, curation checks, pilot generation, and artifact summaries. It consumes existing runtime interfaces through local path dependencies; runtime packages do not import ML code.

## Non-Goals

- Qwen, LFM, MLX, llama.cpp, vLLM, model download, teacher API calls, token spend, SFT, QLoRA, RL, or learned-model evaluation;
- semantic-embedding or LLM-judge deduplication presented as implemented without a frozen model and threshold;
- FastAPI, PostgreSQL, Temporal, PydanticAI, services, persistence, retries, or production deployment;
- frontend, browser, Gmail, LiveKit, telephony, real-Provider integration, credentials, or consumer PII;
- multi-turn stochastic dialogue, a production dataset, a dataset card, or a claim that 128 scripted trajectories are sufficient for training;
- changes to canonical Phase 00B contracts or Phase 01B simulator semantics unless a demonstrated incompatibility blocks this phase.

## Acceptance Criteria

1. `make data-pilot` emits a deterministic Phase 02 cost/quality report without a network or external-model call.
2. `make data-pilot-check` regenerates and verifies the committed schema, manifests, report, and review sample and rejects artifact drift.
3. The accepted manifest contains exactly 128 trajectories across all 32 scenarios, 16 families, two Provider configurations, and the inherited 80/24/24 train/development/test trajectory counts.
4. Exactly eight intentionally invalid candidates are quarantined, collectively proving missing provenance, unapproved license, PII, forbidden-field leakage, exact duplicate, cross-split semantic collision, split mismatch, and invalid verifier outcome rejection.
5. Accepted provenance completeness is 100%; every record binds the Phase 01B split-manifest hash, source/license, family/entity/configuration versions, derivation parent, generator snapshots, prompt/config hashes, simulator version, verifier result, review state, and content hash.
6. Accepted records have zero detected PII, zero forbidden model-facing fields, zero exact duplicates, zero cross-split exact/semantic collisions, and zero invalid or false-completion verifier outcomes.
7. Input reordering produces byte-identical accepted/quarantine manifests, report fingerprints, and selected review sample.
8. The committed review sample contains 16 redacted records selected deterministically across all families and remains explicitly `pending_human`; the annotation guide defines acceptance, rejection, escalation, PII, disclosure, completion, and uncertainty labels.
9. The cost/quality report records zero external calls/tokens/cost, separates automated audit from pending human review, sets `training_ready=false`, and limits its expansion decision to the Data Factory.
10. Existing Phase 01A/01B commands and tests pass unchanged; `make preflight` includes the ML lock and Phase 02 artifact gate and passes.
11. The complete diff receives independent review, accepted findings are remediated, and exact evidence is appended to `harness/build-log.md`.

## Stop Condition

After the Phase 02 pull request passes CI and Sol's final integration review and is squash merged, stop. Phase 03 baselines, teacher-backed data expansion, model selection, training, and evaluation require a new explicit user gate.
