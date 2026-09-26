# ProxyLoop v3: Training

Legend: [O] observed, [E] estimate (hyperparameters are starting points, not results), [P] proposed.

## 0. Changes from v2
| Area | v2 | v3 |
|---|---|---|
| First training | V2, after V1 is complete | **S0 `make pull-through`**: a tiny non-zero BF16 LoRA on real in-harness turns, served through vLLM, **no claim**; re-run on every contract change |
| Teacher clock | `teacher_dilated` | **wall clock**; no dilation |
| On-policy states | one conditional DAgger round after V2 selection | **offline teacher relabelling of student-visited states from S3 on** |
| Scale | a fixed 3.5k candidate episodes | **learning curve** at 100/300/1,000 episodes (LOFO, 6 folds); the S4 scale comes from the curve |
| Mixture | 30 % `talkact_v1` share of portal episodes | a mixture set from the **measured failure share** (S3); the `talkact_v1` share is set in S4 by a dev check |
| Filters | F2/F3 collided on public = private values; context-blind F8; unaudited failed prefixes; rejected candidates as "future data" | F3 exempts declassified values; F8 is context-keyed; failed-prefix truncation is causal and audited; counterfactual rows are flagged and never world-filtered |
| Context | drop samples over 6,144 tokens | the **shared renderer budget** (ARCHITECTURE §6.3) applies identically at data time and serve time; nothing is dropped |
| Attestation | greedy challenge-set hashes | **per-shard sha256** plus a logprob liveness check |
| Accounting | spend ledger | **cost per useful example** per data source and curve point |

## 1. What the student learns (unchanged thesis, sharpened)
Fast learns **protocol discipline under pressure** on both lanes. Every item below is observable in a bundle.

**User lane:**
- relay every revealed fact, typed and exact, within one generation;
- relay a stop or mind change as `@slow: revoke` at once;
- explain an approval card faithfully, with its numbers;
- never claim completion unless `CASE STATUS` is `VERIFIED_*`.

**Counterparty lane:**
- follow the GUIDE move;
- ask for the read-back and get every required field stated;
- stall with `@hold` at decision points;
- relay offer terms as `CP_UPDATE`;
- answer only from public context;
- keep speech short and streamable.

Fast does **not** learn negotiation decisions; those are Slow's. Labels come from the teacher acting in real episodes, or the teacher labelling real student states. They never come from an oracle act table (v0's failure [O packet §3.1: 499 samples were dropped for disagreeing with a scripted oracle act]).

## 2. Data sources (all through `run_session`, I1)
### 2.1 Teacher-in-harness episodes (wall clock)
| Field | Value |
|---|---|
| `fast_user`, `fast_cp` | `sonnet-as-fast` (`claude-sonnet-5` via the relay, temperature 0.7, `max_tokens=160`, no tools) |
| `slow` | `claude-sonnet-5`, the same as in evaluation |
| world | Gemini Flash Ear/Mouth/SimUser; piloted (S3) or train-split (S4) families only |
| clock | wall. The teacher's slower TTFS is real to the world. `teacher_ttfs` vs `student_ttfs` and cp strikes per episode are reported (RISKS R5) |
| decision points | K = 3 candidates [E] at kernel-detected points: a rep offer relayed, a PIN request heard, a pending approval, a user correction or stop. One candidate that passes the view-local filters is **executed**; the others are stored with `counterfactual=true` and are **not trained** in v3 |

**Fast-role constraints, enforced by the harness:** the teacher receives exactly `render_messages(view, profile)`; it never sees the mandate, protected values or the other lane; its output is parsed by the student parser (invalid output is resampled up to twice, and counted); and its speech goes through the same Speaker, fence and release gate.

### 2.2 Student rollouts relabelled offline (S3 on)
1. The student (C2 base, then the latest curve adapter) plays both lanes on fresh piloted/train instances, and **execution follows the student**.
2. For every student `fast.request`, the stored `FastView` is re-rendered and the teacher is queried offline (`render_messages` → Sonnet → parse).
3. The label is kept if it passes the **view-local** filters (§4: F1, F2, F3, F4-lexical, F5, F6, F7). Rows get `source=relabel, counterfactual=true`.

A relabel row whose teacher output differs materially from the student's action (a different directive set, a different relayed value, or a hold vs no hold) is flagged `disagreement=true`. These are the states v2 feared the student would visit without supervision.

### 2.3 Hard cases (train families only; at most 25 % of instances)
Parameter perturbations proposed by Sonnet and validated deterministically (schema-valid, and the reference predicate proves the instance completable), unchanged from v2 [O `completable`, `negotiation_evaluation.py:117`]. Never on dev or test families.

## 3. Provenance (per trajectory → the manifest row)
Recorded per trajectory:
- teacher model, echoed model ids and request ids;
- git sha, contract version, renderer fingerprints, Slow tool-schema hash;
- world version, `family@version`, instance hash, persona;
- `verifier_version`, `filter_version`;
- source (`teacher_exec` | `relabel` | `hard_case`), `counterfactual`, `disagreement`;
- `gen_params` and the cfg hash;
- spend by role.

The dataset manifest aggregates the rows, and its hash goes into the adapter card.

## 4. Filters (deterministic or world-grounded; `filter_version`)
| ID | Rule | Applies to |
|---|---|---|
| F1 | Grammar valid and canonicalisable; directives legal for the lane | all rows |
| F2 | Every spoken number appears in the rendered view | all rows |
| F3 | **(repaired)** cp lane: no private value that was **not public at that seq** (declassified values are exempt, which removes the F2/F3 collision). Executed rows: the turn is not in the `cause_ids` chain of a realised harm; the episode is truncated before such a turn | all / executed |
| F4 | At a world-labelled cp decision point: executed rows need no RepEar `accept` on the turn plus `@hold` or a deflection; relabel rows need no acceptance-lexicon hit plus `@hold` or a deflection | executed / relabel |
| F5 | cp ≤ 40 spoken words and ≤ 3 sentences; user ≤ 60 words | all rows |
| F6 | Relay completeness against **ground truth**: every value the triggering user message revealed (`user.sim.revealed`) and every offer term the rep voiced (`rep.mouth` intent) is relayed with the correct value, or the turn holds | all rows |
| F7 | No completion claim unless the view's `CASE STATUS` is `VERIFIED_*` | all rows |
| F8 | **(repaired, context-aware)** dedup key = (lane, trigger type, sha of the view minus all but the last 2 transcript lines, normalised completion); near-duplicates (MinHash ≥ 0.9) removed only within a key bucket; a global cap of 0.5 % of rows per normalised completion | all rows |

**Episode rules.**
- Executed turns are kept from safe-success episodes and from verified correct declines.
- **Failed-prefix rule (causal, audited):** keep executed turns strictly before the earliest `fast.turn` in the cause chain of the first realised harm. For non-harm failures, keep turns before the first world-labelled decision point the episode failed. Each dataset build audits 30 sampled prefixes, checked by the root against the replay: "does any kept turn contribute to the failure?". The error rate goes into the dataset card, and above 10 % the rule is revised before training.
- `@wait` and filler turns are capped at 10 % of rows.

`make data` prints the funnel per filter × family × source.

## 5. Scale: the learning curve (S3) and the S4 scale
**S3 pool (piloted families 1–6) [E]:**
- 1,200 teacher episodes (200 per family) and 600 relabelled student rollouts;
- nested subsets n ∈ {100, 300, 1,000}, drawn by salt and stratified by family;
- for fold k, the subset comes from the 5 other families only.

That is 18 LOFO adapters plus 1 in-family adapter at n = 300 (B's check). One recipe for every size (§8) and the last checkpoint only: the curve measures data, not selection.

**The S4 scale n\*** is the smallest n whose `Δ̂_LOFO` lies within the C2 − C2r noise floor of the largest measured n. If the curve still rises from 300 to 1,000 by more than the noise floor, n\* = min(3,000, the next point) [E], with a spend projection shown to the user.

**Mixture from the measured failure share.** Sampling weights over (family, lane, decision type) are proportional to the share of C2 failures that A4 teacher-repair converts (EVAL §8.3), with a floor of 5 % and a cap of 35 % per family. The relabel share defaults to 40 % of rows at n ≥ 300 [E]. The S3 report states whether relabel rows moved the in-family curve.

## 6. Dataset schema and sample construction
```jsonc
// data/sft/<dataset_id>/samples.jsonl (one Fast turn per row)
{"sample_id":"…","dataset_id":"lc-300-fold3","run_id":"…","event_id":"…:184","family":"cp-hidden-fee-readback",
 "split":"train","lane":"cp","profile":"pl_cp_v1","fingerprint":"…","view_sha":"…",
 "completion":"Could you read me back every charge, including any one-time fees?\n@hold offer",
 "source":"teacher_exec|relabel|hard_case","counterfactual":false,"disagreement":false,"decision_point":true,
 "filters_passed":["F1",…],"teacher":{"model":"claude-sonnet-5","request_id":"…"}}
```
```python
view    = FastView.model_validate_json(bundle.prompts[row.view_sha])
prompt  = contract.protocol.render_prompt(view, row.profile, tok)       # applies the shared context budget
assert row.fingerprint == contract.protocol.fingerprint(row.profile)    # otherwise: re-render, flagged rerendered=true
completion = contract.protocol.format_turn(contract.protocol.parse(teacher_raw)) + "<|im_end|>"
```
Loss is on completion tokens only. P5 runs on the first batch of every run and aborts on a mismatch.
- Only train or piloted families are admitted. `make dataset-check` fails on a dev or test family, on an instance-hash collision, or on a 13-gram overlap with external or held-out text.
- Committed: the manifest, the dataset card and a 50-row sample. The rows themselves live on a Modal Volume.

## 7. Cost per useful example
`cpue = (teacher + Slow + world relay USD + GPU USD attributable to generation) / useful_rows`. A **useful row** passes all filters and is a decision-point row, a relay-bearing row, or a relabel row with `disagreement=true`. It is reported per source and per curve point in `docs/results/s3-curve.json`, and projected for n\* before the S4 generation.

## 8. BF16 LoRA recipe (Modal H100-80GB; one pinned configuration, ADR-0003) [E unless marked]
| Setting | Value |
|---|---|
| Base | `Qwen/Qwen3.5-9B` at a pinned revision; vision tower frozen and untargeted; text only |
| Targets | attention `q,k,v,o_proj` + GDN `in_proj_qkv,in_proj_z,in_proj_b,in_proj_a,out_proj` + MLP `gate,up,down_proj`, **restricted to what vLLM serves** (ADR-0002 ladder) |
| r / α / dropout | 32 / 64 / 0.05 (pull-through: 8 / 16) |
| Optimiser | AdamW, lr 1e-4, cosine, 3 % warmup, wd 0, clip 1.0 (pull-through: lr 2e-4, 40 steps) |
| Batch | effective 64 sequences; micro-batching by a token budget |
| Sequence | max 4,096 tokens [E]. The renderer budget bounds prompts; any overflow is a **bug** (the run aborts), never dropped |
| Epochs | 2 (curve); S4: 2–3 with checkpoints every 0.5 epoch |
| Kernels | fused GDN kernels (flash-linear-attention, causal-conv1d) verified active in S0-MOD-02; a torch fallback aborts the run |
| Cost | n = 1,000 ≈ 12k rows ≈ 30M tokens/epoch → ≈ 2–3 h/epoch on H100 at 3–5k tok/s [E] |

**S4 checkpoint selection:** the highest dev safe success (dev families + held-out-instance dev of train families). Ties go to the earlier checkpoint, then to the lower false-completion claim rate. Loss and agreement are never used; they saturated in v0 [O 0.983 agreement vs 0/240].

## 9. `make pull-through` (S0 on; plumbing only, "no claim")
| Mode | When | Steps |
|---|---|---|
| `full` | the renderer fingerprint changed, or a new stage opens | (1) choose ≤ 60 real Fast turns from the latest `evidence/` bundles whose fingerprint equals the current one. **S0: base-9B turns** (teacher runs are not allowed before S1's Guard; PLAN §9 E1). **S1 on: teacher turns.** (2) Build rows through §6 and run P5. (3) Train the pull-through recipe on Modal. (4) Load the adapter into the vLLM LoRA slot `Qwen3.5-9B-pl-pt-<fp8>`. (5) Liveness: the mean `prompt_logprobs` difference from base on 5 fixed pairs exceeds 1e-3 nats. (6) Run one product-path session with both lanes on the adapter. (7) `evidence-check --claim`. (8) Write `docs/results/pull-through.json` `{fingerprint, dataset_hash, adapter_shards, liveness, run_id, claim: "none"}` |
| `verify` | any other contract change | steps 4–8 with the existing adapter |

## 10. Export and serving artefacts
- `adapters/<id>/` contains the PEFT config, the adapter files and `adapter_card.json` (dataset hash, recipe, fingerprint, **shard sha256s**, dev results).
- Serving follows the ADR-0002 ladder. For merged BF16, a merge-equivalence check requires greedy token agreement ≥ 99 % on 200 dev prompts, with prefix caching off. This is a model-equivalence check, **not** an attestation.
- `/pl/attest` and the shard hashes are stamped into `session.started`, and `evidence-check` compares them with the card.
- Metal or quantised local artefacts are out of scope until S5+. They never produce headline numbers.

## 11. Commands (L = live keys, G = GPU; root-run)
| Command | Flags | Output |
|---|---|---|
| `make pull-through MODE=full\|verify` | L G | `docs/results/pull-through.json` + a bundle |
| `make data SPEC=<spec>` | L | `data/sft/<id>/manifest.json`, funnel, dataset card |
| `make relabel RUNS=<glob>` | L | relabel rows + provenance |
| `make dataset-check` | – (CI) | split, contamination and fingerprint checks |
| `make train DATASET=<id> RECIPE=<name>` | G | adapter + card (P5 must pass) |
| `make curve` | L G | 19 adapters + `docs/results/s3-curve.json` |
| `make select` (S4) | L G | `docs/results/s4-dev-selection.json` |
| `make export` | G | adapter/merged artefacts, liveness, equivalence |
