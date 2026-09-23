# Phase 03C Stage 3 decision — independent review

Reviewer: project `reviewer` agent (Opus, high effort), read-only, not the
session that produced the diff. Recorded by the root orchestrator.
Target: the Stage 3 close-out on `feat/phase-03c-stage2-cloud-run` — the
re-scoring script, the decision record, `docs/ml-evidence.md`, `README.md`,
the Makefile target list and the returned artifacts.

**Verdict: Request Changes.** All findings addressed or ruled on below.

## Independently confirmed sound

- **The re-scoring is canonical and reproducible.** The reviewer re-ran both
  rounds and got byte-identical output to the committed artifacts, with
  `cloud disagreements: 0`. `build_index` faithfully reproduces
  `build_heldout_rows` (seeds 950–959, six non-training families, 2 configs
  x 10 seeds x 2 positions = 240) and the committed prompt set covers only
  the ten training families, so `index.setdefault` cannot mask a held-out id.
  All 23 repository metric fields participate in the comparison; only two
  cloud-derived fields are unmatched and both are covered by repository
  fields. `stale_pin_violation` is constant on the cloud side and really
  computed locally, so the zero is incremental evidence, not a tautology.
- **The `split="development"` hard-code is safe.** `run_phase03c_row` and its
  callees read `example.view`, `public_observation` and `target` only; the
  three `.split` reads in `phase03c_experiment.py` are on other code paths.
- **The restricted-rows argument holds.** GO_PROMPT_ONLY's second condition
  fails at 34 points even on the truncation-favourable numbers, and
  GO_DISTILLED rests on A1 and A3, both 240/240 `finish_reason: stop`.
- **Scope.** No frozen module and no `configs/lora-8b.json` change; the log
  authorizes no promotion.
- Most published figures were re-derived from the artifacts and matched,
  including the per-family table, 14/120 `confirm`, the truncation counts,
  81/126 and 214/218, the 0.500 majority-class baseline, and 2,560 = 960 +
  1,600.

## Findings and disposition

| # | Severity | Finding | Disposition |
|---|---|---|---|
| B1 | Blocking | "Zero policy violations" is structurally incomplete on the held-out set (no row can trip the disclosure detector) and the same run's dev round shows the distilled arm leaking a restricted field 4/400, which the write-up omitted entirely | **Ruled on by the root orchestrator** (`harness/log/phase-03c-stage2-stage3.md`, "Root-orchestrator ruling"). Decision unchanged; qualification added as a sixth item in `docs/ml-evidence.md` and carried into `README.md` |
| B2 | Blocking | "1,349 optimizer steps" contradicts every artifact; the manifest ends at step 1,350 | Fixed everywhere. The figure came from a pre-run estimate in the runner log and had been copied forward |
| I1 | Important | "the three logs" was false: `eval-heldout.log` and `eval-dev.log` were caught by the global `*.log` rule | Fixed: `.gitignore` negations added, both logs committed |
| I2 | Important | README's "What is implemented" table still described the 03B `NO_GO` as the state of post-training | Fixed |
| I3 | Important | README asserted the Fast model **is** project-trained while the same page says nothing is promoted | Fixed: restored to "meant to be" and stated that the runtime still runs the untuned model |
| I4 | Important | Cost figures were mutually impossible (22.25 both as the run and as the phase total, against 4.16 for the smokes) | Fixed: phase cumulative 22.25, run about 18.09, and flagged as a console reading with no artifact |
| I5 | Important | No check target for the canonical path, and `make test` misses the cloud manifests because `run_phase03c_training.py` globs one directory level | Partly fixed: `make phase03c-rescore-check` now replays both rounds and fails if the committed re-scored reports drift, and is wired into `make test`. The manifest glob is a separate defect in a Stage 2 script and is left for a bounded follow-up rather than widened at the gate |
| I6 | Important | The log asserted `status.toml` had returned to `idle` while it still said `blocked` | Fixed: the gate action was taken; `validate_layout` then required `active_contract` to be cleared too |
| m1 | Minor | The `CLOUD_ALIAS` comment was wrong (the cloud report carries both spellings) and the fold relied on them happening to be equal | Fixed: comment corrected and the two copies are asserted equal per row |
| m2 | Minor | `clustering_note` asserted one oracle act per family in prose without checking | Fixed: the script now verifies it and refuses to write otherwise |
| m4 | Minor | Contract deviations were not registered at the gate | Fixed: a deviation table is in the log |
| m5, m6 | Minor | The 32,000 figure was presented as the sampling pool, and "8,003 samples" conflated calls with samples; the aborted generation run was not mentioned | Fixed in `docs/ml-evidence.md` |
| m7 | Minor | "train loss fell tenfold (1.219 → 0.129)" matched no endpoint | Fixed: 1.219 at step 10 to 0.133 at step 1,350, minimum 0.116 at step 1,230. The eval-loss rise is also corrected from 12 % to **16.8 %**: the earlier figure came from a log capture that stopped at epoch 2.22 |
| m8 | Minor | The `smoke-01` artifacts were committed but unlisted | Fixed |
| m9, m10 | Minor | GO_PROMPT_ONLY wording, and the middle tie-break in checkpoint selection was omitted | Fixed in both documents |
| m3, m11 | Minor | `build_index` renders train-split prompt rows as `development`, harmless for this input; the script imports a sibling script under two module names | Accepted, not fixed. Neither affects a published number; both are noted here so a future change knows |

## Note on what a review cannot check

Modal billing is not a repository artifact. The 22.25, 4.16 and 30 figures
are console readings by the operator and the reviewer said so rather than
passing them. The documents now label them as such.
