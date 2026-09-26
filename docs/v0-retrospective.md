# v0 retrospective

v0 was built from 2026-08-22 (its first commit) to 2026-09-25 and is frozen at the git tag `v0-legacy` (commit `514fe31`). This page says what it built, what it measured, which résumé numbers it could not support, and why the project was rebuilt. Every number below cites a committed file at the tag, written as `v0-legacy:` followed by the path (browse one with `git show v0-legacy:<path>`). Sentences that begin "we infer" or "in our reading" are the rebuild's interpretation, not v0 measurements.

## What was built
- A Temporal-backed case runtime with typed commands and events, Postgres storage, and a scripted provider simulator for telecom bill negotiation (`v0-legacy:runtime/`, `v0-legacy:contracts/`).
- A Next.js web client with intake, progress, offer, approval and evidence panels over one HTTP seam (`v0-legacy:apps/`).
- An ML track (`v0-legacy:ml/`): a data pipeline, LoRA smoke runs, teacher distillation of Qwen3-8B with BF16 LoRA on one NVIDIA A100 (`v0-legacy:data/experiments/phase-03c/training/cloud-run-01/train/run-manifest.json`: `base_model.model`, `config.bf16`, `gpu`), and a local MLX Fast gateway.
- A development harness: phase contracts, per-PR logs, review artefacts and a gate script (`v0-legacy:harness/`).
- `voice/` was a placeholder, never built (`v0-legacy:docs/architecture.md`).

The architecture is described in `v0-legacy:docs/architecture.md`, the ML evidence in `v0-legacy:docs/ml-evidence.md`, and the limitations in `v0-legacy:docs/limitations.md`.

## The honest numbers

### The trained path worked
Phase 03C distilled Qwen3-8B on oracle-filtered teacher data. On 240 held-out rows, in the prompt format the adapter was trained on, dialogue-act agreement with the oracle rose from 130/240 = 0.542 untuned (arm A1) to 236/240 = 0.983 distilled (arm A3), and the run's decision was `GO_DISTILLED`. Artefacts: `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-rescored.json` (`arms.A1.aggregate.dialogue_act_accuracy`, `arms.A3.aggregate.dialogue_act_accuracy`, `arms.A1.label`) and `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-report.json` (`decision.decision`).

v0's own caveat travels with this number: every family's rows share one oracle dialogue act, so 6 distinct decision rules carry the result and the row-level Wilson intervals are optimistic (`v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-rescored.json`, `clustering_note`).

Rerun locally with MLX in the same trained format, the adapter reproduced 0.983 (`v0-legacy:data/experiments/phase-03c/local-parity/parity-report.json`, `verdict.distilled_local_act_agreement`). That local run is the baseline for the next section.

### The product path delivered nothing
Claim boundary, in v0's own words: the numbers in this section were "generated locally with MLX on one Apple-silicon machine, and replayed through the runtime delivery rules offline" (`v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json`, `claim_boundary`). So no consumer was involved. They are cited here as a historical audit of v0; v3 takes no headline number from a Metal artefact (NORTH_STAR, non-goals).

The same adapter, given the same 240 rows through the product's own input path, delivered **0/240** lines (measured locally with MLX, replayed offline). 40 rows were refused before the model was called (`gateway_unrenderable`) and the gate rejected the other 200. Act agreement on that path was 157/240 = 0.654, and the untuned model delivered 8/240. Artefact: `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json` (`arms.distilled.summary.delivered_line`, `.delivery_stages`, `.act_agreement_true_oracle`; `arms.untuned.summary.delivered_line`).

The 0/240 is attributable to the gate. v0's disclosure gate (`fast-gate-v1`) withholds numbers the strategy does not allow and rejects dialogue acts it does not allow. On the product path all 200 gated outputs carried `fast_gate_dialogue_act` (200/200) and `fast_gate_number_not_allowed` (200/200), and 181/200 also carried `fast_gate_completion`. On the trained path, where no row was refused, the same gate rejected all 240 distilled outputs (`trained_path_delivered_line` 0/240; `trained_path_delivery_stages` = `gate_rejected` 240). Artefact: `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json` (`arms.distilled.summary.gate_rejection_codes` and the two `trained_path_*` fields). v0's own reading: "the gate, not only the renderer, blocks the model", because the model was trained on confirm/counter acts and minor-unit arithmetic, which the gate withholds by design (`v0-legacy:docs/ml-evidence.md`, section "The product path: a negative result").

The path difference accounts for the agreement drop from 0.983 to 0.654. Net, 79 rows were lost (80 lost, 1 gained): 40 refusal-transfer rows were refused before the model, and 40 unsupported-action rows lost because the product observation carries no `applied_changes`, so the model answered confirm where the true act is counter (`v0-legacy:docs/ml-evidence.md`, "Why act agreement falls from 236 to 157").

The adapter stayed a local opt-in candidate and was never promoted (`v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json`, `labels.distilled` and `claim_boundary`).

### The self-audit found two unsupported evidence claims
The v0 repository audit (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (e)) records two problems:
- The r1 Slow prompts contained the oracle's label as an approved `accept_offer` on exactly the 10 accept episodes, while the plan's 03A1-B row still said "full gate passed" (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (e)). At the tag that row carries the correction: "Complete with erratum: the r1 Slow prompts carried the oracle's accept label on the 10 accept episodes" (`v0-legacy:PLANS.md`, line 22).
- The r5 system prompt transcribed the oracle's decision precedence, and its five successes were exactly the five one-boolean rules (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (e)). At the tag the r5 row reads "rule-following under oracle-rule parity, not independent reasoning" (`v0-legacy:docs/ml-evidence.md`, section "Results so far").

In our reading, both show how a scripted evaluation can hand the model the answer without anyone noticing until an audit.

## Résumé numbers withdrawn
These figures circulated in résumé drafts. They are withdrawn.
- **`58→67` and `6→2` (no artefact).** We found no text file at the tag that contains either transition: each of these patterns, run as `git grep -I -i -E '<pattern>' v0-legacy`, returned no match: `58[[:space:]]*%?[[:space:]]*(→|->|=>|to|–|—)[[:space:]]*67`, `(^|[^0-9.])6[[:space:]]*(→|->|=>|to|–|—)[[:space:]]*2([^0-9.]|$)`, `from[[:space:]]+58[^0-9]`, `from[[:space:]]+6[[:space:]]`. v0's ML evidence page (`v0-legacy:docs/ml-evidence.md`) reports neither.
- **"4-bit QLoRA" (misdescribes the result).** v0 did train on a 4-bit base: the Phase 03B smoke was LoRA on `mlx-community/Qwen3-4B-Instruct-2507-4bit` and ended `NO_GO_STOP_PHASE03B` (`v0-legacy:data/experiments/phase-03b-qlora-smoke/manifest.json`, `base_checkpoint.model`; `v0-legacy:data/experiments/phase-03b-qlora-smoke/results/comparison.md`), and the Phase 03C smoke records `"quantization": "4bit"` (`v0-legacy:data/experiments/phase-03c/training/smoke/run-manifest.json`, `base_checkpoint.quantization`). The result that worked, 0.542→0.983, used BF16 LoRA on Qwen3-8B (`v0-legacy:data/experiments/phase-03c/training/cloud-run-01/train/run-manifest.json`, `config.bf16`, `base_model.dtype`), and v0's defaults record the move from 4-bit QLoRA to BF16 LoRA (`v0-legacy:docs/decisions/2026-08-22-implementation-defaults.md`, amendment 2026-09-21). The phrase is withdrawn because it misdescribes the result, not because 4-bit never ran.

The v3 résumé lines are fixed in `NORTH_STAR.md`, and every number they carry renders from a committed report (I10).

## Root causes
1. **Two execution paths.** Training and evaluation rendered prompts in one format; the product rendered observations through another, and no product prompt equalled its trained prompt (`v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json`, `divergence.prompt_identical_rows` = 0). That difference explains the agreement drop above. Earlier, the audit had found that the product runtime never used model output at all: its model seams were evaluation-only (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (b)).
2. **A gate and a training target that contradicted each other.** The gate withholds by design the acts and arithmetic the model was trained to produce, and it rejected every distilled output that reached it, on both paths (`v0-legacy:docs/ml-evidence.md`; `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json`). In our reading, nothing forced the two to be measured together until the end of Phase 03C.
3. **Scripted evaluation looked like progress.** The audit found that the verifier and evaluator scored agreement with a script rather than provider state, so 22/32 "valid outcomes" were "exact-match-with-script numbers" (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (c)), and that two headline claims leaked or transcribed the oracle (finding (e)). We infer that the missing requirement was a trace from a real model response to what a listener heard.
4. **Numbers were typed, not generated.** The audit found that `baselines-check` and `validity-smoke-check` recomputed fingerprints over a report's own rows, so an edited 5/6 → 6/6 would still pass, and it lists the prose claims that their artefacts falsify (`v0-legacy:docs/research/2026-09-21-repository-audit.md`, finding (e) and the "Falsifies" lines). In our reading, the withdrawn résumé figures are the same failure outside the repository.
5. **The process outweighed the product.** The build log alone reached 143,983 bytes (`git cat-file -s` on `v0-legacy:harness/build-log.md`). In our reading, phase contracts, per-PR logs and review artefacts grew faster than the product path.

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
| Plan with the r1 erratum | `v0-legacy:PLANS.md` |
| Self-audit | `v0-legacy:docs/research/2026-09-21-repository-audit.md` |
| Implementation defaults | `v0-legacy:docs/decisions/2026-08-22-implementation-defaults.md` |
| Phase 03C held-out report (decision) | `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-report.json` |
| Phase 03C held-out report (rescored) | `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/eval/heldout-rescored.json` |
| Phase 03C training manifest | `v0-legacy:data/experiments/phase-03c/training/cloud-run-01/train/run-manifest.json` |
| Phase 03C product-path report | `v0-legacy:data/experiments/phase-03c/local-parity/product-path-report.json` |
| Phase 03C local/cloud parity | `v0-legacy:data/experiments/phase-03c/local-parity/parity-report.json` |
| Phase 03C smoke (4-bit base) | `v0-legacy:data/experiments/phase-03c/training/smoke/run-manifest.json` |
| Phase 03B QLoRA smoke | `v0-legacy:data/experiments/phase-03b-qlora-smoke/manifest.json`, `v0-legacy:data/experiments/phase-03b-qlora-smoke/results/comparison.md` |
| Terms hash (ported in S0-SYS-01) | `v0-legacy:runtime/packages/contracts/src/proxyloop_contracts/material_terms.py` |
| Offer policy (ported) | `v0-legacy:runtime/packages/contracts/src/proxyloop_contracts/offer_policy.py` |
| Salted split (ported) | `v0-legacy:runtime/packages/provider_simulator/src/proxyloop_provider_simulator/negotiation_splits.py` |
| Confirmation ledger modes (ported) | `v0-legacy:runtime/packages/provider_simulator/src/proxyloop_provider_simulator/negotiation.py` |
| Worktree inventory at the reset | `docs/v0-worktrees.md` |
| Git-ignored v0 artefacts (not in the `v0-legacy` tag) | `~/Desktop/proxyloop-v0-archive/` (`main-tree-ignored/`, `from-agent-*/`) |
