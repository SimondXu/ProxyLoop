# v0 retrospective

v0 was built from 2026-08-21 to 2026-09-25 and is frozen at the git tag `v0-legacy` (commit `514fe31`). This page says what it built, what it measured, which résumé numbers it could not support, and why the project was rebuilt. Every number below cites a committed file at the tag, written `v0-legacy:<path>` (browse it with `git show v0-legacy:<path>`).

## What was built
- A Temporal-backed case runtime with typed commands and events, Postgres storage, and a scripted provider simulator for telecom bill negotiation (`v0-legacy:runtime/`, `v0-legacy:contracts/`).
- A Next.js web client with intake, progress, offer, approval and evidence panels over one HTTP seam (`v0-legacy:apps/`).
- An ML track with a data pipeline, a QLoRA smoke run, teacher distillation of Qwen3-8B with BF16 LoRA on one cloud GPU, and a local MLX Fast gateway (`v0-legacy:ml/`, `v0-legacy:data/experiments/`).
- A development harness: phase contracts, per-PR logs, review artefacts and a gate script (`v0-legacy:harness/`).
- `voice/` was a placeholder, never built (`v0-legacy:docs/architecture.md`).

The architecture is described in `v0-legacy:docs/architecture.md`, the ML evidence in `v0-legacy:docs/ml-evidence.md`, and the limitations in `v0-legacy:docs/limitations.md`.

## The honest numbers

### The trained path worked
Phase 03C distilled Qwen3-8B on oracle-filtered teacher data. On 240 held-out rows, in the prompt format the adapter was trained on, dialogue-act agreement with the oracle rose from 130/240 = 0.542 untuned (arm A1) to 236/240 = 0.983 distilled (arm A3). The run's verdict was `GO_DISTILLED`.
- Artefact: `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-rescored.json` (`arms.A1.aggregate.dialogue_act_accuracy`, `arms.A3.aggregate.dialogue_act_accuracy`).
- Prose: `v0-legacy:docs/ml-evidence.md` (the opening paragraph).

### The product path delivered nothing
The same adapter, reached through the product's own input path, delivered **0/240** lines to a consumer. 40 rows were refused before the model was called (`gateway_unrenderable`); the disclosure gate rejected the other 200 after generation, each carrying the `fast_gate_number_not_allowed` and `fast_gate_dialogue_act` codes. On that path act agreement fell to 157/240 = 0.654, and the untuned model delivered 8/240. Artefact: `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json` (`arms.distilled.summary`, `arms.untuned.summary`); prose: `v0-legacy:docs/ml-evidence.md` (the opening paragraph).

The adapter stayed a local opt-in candidate and was never promoted. The consumer always saw the fallback line.

### The self-audit found two unsupported evidence claims
`v0-legacy:docs/research/2026-09-21-repository-audit.md` (finding (e)) records two problems:
- the r1 Slow prompts contained the oracle's label as an approved `accept_offer` on exactly the 10 accept episodes, while the plan still recorded the gate as passed (`v0-legacy:PLANS.md`);
- the r5 "diagnostic success" was rule transcription, not reasoning.

Both were disclosed and corrected in v0. They are listed here because they show how scripted evaluation can quietly leak the answer.

## Résumé numbers disowned
These numbers circulated in résumé drafts and are **not supported by any committed artefact**. They are withdrawn:
- **`58→67` and `6→2`:** no file at the tag contains either figure, in any form (checked with `git grep` over the whole tag).
- **"4-bit QLoRA":** it appears only as an early implementation default (`v0-legacy:docs/decisions/2026-08-22-implementation-defaults.md`). The one QLoRA run was the Phase 03B smoke, which ended `NO_GO_STOP_PHASE03B` (`v0-legacy:data/experiments/phase-03b-qlora-smoke/results/comparison.md`). The result that did work (Phase 03C) used BF16 LoRA, and the same decisions file records the switch away from 4-bit QLoRA.

The v3 résumé lines are fixed in `NORTH_STAR.md`, and every number they carry renders from a committed report (I10).

## Root causes
1. **Two execution paths.** Training and evaluation rendered prompts in one format; the product rendered observations through another (`PHASE_03B_PUBLIC_SAFE_OBSERVATION_V1`). The model was good at the first and never exercised through the second until the end. The difference between 0.983 and 0/240 is the gap between those paths (`v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json`).
2. **A gate designed for a scripted world.** The post-model disclosure gate banned every number the model spoke, so any real negotiating line failed. The scripted evaluation never sent real model text through it.
3. **Fakes looked like progress.** Scripted Fast/Slow replays and recorded fixtures passed every gate. Nothing forced a real model response to be traced to what the listener heard.
4. **Numbers were typed, not generated.** Prose and résumé drafts drifted away from the artefacts, and the audit had to reconcile them by hand.
5. **The process outweighed the product.** Phase contracts, per-PR logs and review artefacts grew faster than the product path. The build log alone reached about 144 KB (`v0-legacy:harness/build-log.md`).

## Lessons carried into v3
1. **One execution path, one renderer.** Demo, data, evaluation, teacher runs and training all go through `run_session` and `contract.protocol` (NORTH_STAR I1, I3).
2. **Measure on the product path from the first commit.** The first real interaction happens in S0, not at the end (PLAN §2, S0-ROOT-05).
3. **Real by default, with provenance.** Fakes live only in `tests/`, and every claim rests on a bundle that traces response → parse → state → heard (I8).
4. **Numbers are generated.** README tables and résumé lines render from report JSON, and CI fails on drift (I10).
5. **A small process.** One state file (`PLAN.md`), ADRs, and the PR description as the log (NORTH_STAR, non-goals).

## Asset index (at `v0-legacy`)
| Asset | Path |
|---|---|
| Architecture | `v0-legacy:docs/architecture.md` |
| ML evidence | `v0-legacy:docs/ml-evidence.md` |
| Limitations | `v0-legacy:docs/limitations.md` |
| Self-audit | `v0-legacy:docs/research/2026-09-21-repository-audit.md` |
| Implementation defaults | `v0-legacy:docs/decisions/2026-08-22-implementation-defaults.md` |
| Phase 03C held-out report | `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-rescored.json` |
| Phase 03C product-path report | `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json` |
| Phase 03C local/cloud parity | `v0-legacy:data/experiments/phase-03c/local-parity/parity-report.json` |
| Phase 03B QLoRA smoke | `v0-legacy:data/experiments/phase-03b-qlora-smoke/results/comparison.md` |
| Terms hash (ported in S0-SYS-01) | `v0-legacy:runtime/packages/contracts/src/proxyloop_contracts/material_terms.py` |
| Offer policy (ported) | `v0-legacy:runtime/packages/contracts/src/proxyloop_contracts/offer_policy.py` |
| Salted split (ported) | `v0-legacy:runtime/packages/provider_simulator/src/proxyloop_provider_simulator/negotiation_splits.py` |
| Confirmation ledger modes (ported) | `v0-legacy:runtime/packages/provider_simulator/src/proxyloop_provider_simulator/negotiation.py` |
| Worktree inventory at the reset | `docs/v0-worktrees.md` |
