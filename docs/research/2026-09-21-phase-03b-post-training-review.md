# Phase 03B post-training review (2026-09-21)

Independent re-read of the Phase 03B QLoRA smoke and its artifacts, written
after the phase closed. It does not change the recorded `NO_GO_STOP_PHASE03B`
decision; it explains what that decision does and does not support and what a
redo must change. Numbers below were re-derived from the committed artifacts.

## What was actually run

| Item | Value | Source |
|---|---|---|
| Task | one JSON `FastModelOutput@1.0` per turn: `dialogue_act` (6 enum), `fact_updates`, `reasoner_request{needed, reason_code}`, `completion_claim`, `response_text`, `action_intent` | `runtime/packages/contracts`, `ml/evaluation/src/proxyloop_evaluation/fast_output.py` |
| Prompt | "compact v2" prompt without the JSON schema; `reason_code` shown as `"string"` although the contract caps it at 256 chars | `ml/evaluation/src/proxyloop_evaluation/phase03b_experiment.py` |
| Training data | 20 train / 6 valid rows, variant 0 of the Phase 02 pilot; all 26 share one goal (9200 → 7500, one provider) | `data/experiments/phase-03b-qlora-smoke/train.jsonl`, `valid.jsonl` |
| Labels | scripted-oracle action mapped through a fixed lookup to canonical strings: 6 distinct targets in train, 2 in valid, both present verbatim in train | `ml/evaluation/src/proxyloop_evaluation/phase03b_readiness.py` (`proposed_fast_target`) |
| Method | MLX-LM LoRA on `mlx-community/Qwen3-4B-Instruct-2507-4bit`; 8 layers, rank 8, scale 16, batch 1, grad-accum 4, **40 iters, LR 1e-5**, seq 2048; ≈2 epochs, **10 optimizer updates**, 2,780 supervised tokens | `data/experiments/phase-03b-qlora-smoke/qlora-smoke.yaml`, `manifest.json` |
| Hardware | Apple M4 Pro 48 GB, ~128 s, 5.4 GB peak | `harness/build/phase-03b-qwen-qlora-smoke.md` |
| Evaluation | 6 dev scenarios (3 families × 2 configs), greedy, max 512 tokens; Arm A = 4-bit base, Arm B = base + adapter | `results/arm-a-untuned.json`, `results/arm-b-qlora.json` |
| Result | A: 1/6 schema-valid, 0/6 E2E; B: 0/6 (`invalid_json` × 6) | `results/comparison.md` |

The adapter weights were not committed, so Arm B cannot be re-scored.

## Root causes, ranked

1. **Evaluation error — the baseline was broken by the Phase 03B prompt, and the parser counted formatting as failure.**
   Re-reading `arm-a-untuned.json`: all 6 raw outputs are syntactically valid
   JSON objects; the schema failures are a `reason_code` longer than 256
   characters because the prompt never stated the limit. The same untuned
   model, with the Phase 03A1 prompt that embeds the full JSON schema, scored
   32/32 schema-valid in r2/r4 and 6/6 in r5. Arm B's 6 outputs are all
   markdown-fenced (```` ```json ````); the adapter's `generate()` calls
   `json.loads` on the raw string with no fence stripping and no constrained
   decoding, so every one was recorded as `invalid_json`. After stripping the
   fence all 6 parse. Neither arm was therefore measured on decision quality.
2. **Scale error — this was not a training run.** 20 examples, 6 distinct
   targets, 10 LoRA updates at LR 1e-5 (an order of magnitude below the usual
   LoRA range). The validation-loss drop (3.89 → 1.71) is memorisation of two
   strings that also appear in train; generated outputs still chose `counter`
   for every episode where the target was `confirm`/`escalate` and still wrote
   long `reason_code` text. The adapter perturbed the first-token prior enough
   to trigger fencing without learning the target format.
3. **Method error — no teacher signal.** Targets are a deterministic lookup
   from an oracle that is already 100% correct on scripted scenarios
   (`data/manifests/phase-03a1-ceiling-report.json`). Imitating six fixed
   strings from ten training families and generalising to three unseen
   families, with one shared goal and no rationale, has no plausible learning
   signal. DPO/RL and teacher generation were declared out of scope up front.
4. **Metric naming.** `_policy_violation` in `phase03b_experiment.py` is
   `dialogue_act != oracle act`; reporting it as a safety metric ("6/6
   violations") overstates what it measures. Strict and fence-tolerant
   parsing were not reported separately, so format swallowed decision.
5. **Mac / MLX was a symptom, not the cause.** The run itself was fine. The
   costs were (a) training on a community 4-bit base rather than the official
   bf16 weights, so nothing transfers to the planned vLLM/CUDA path, and (b)
   a "local budget" framing that shrank the experiment to 40 iterations. Moving
   the same data, prompt, and parser to a cloud GPU would not change the
   outcome.
6. **Leakage / alignment.** Family-level train/dev/test split was correct
   and the 03A1-V fee-predicate parity gap was closed in the 03B prompt. But
   valid targets ⊂ train targets makes val loss meaningless, and the Phase 02
   human-review sample includes 3 test-family records (already disclosed).
7. **Decoding.** `Qwen3-4B-Instruct-2507` is non-thinking-only, so thinking
   mode was not a factor. Missing: length constraints in the prompt, fence
   tolerance, constrained JSON decoding (already planned via vLLM), and a
   check that the training chat-template rendering matches inference
   rendering.
8. **Process.** Six review rounds went to evaluator provenance and
   tamper-resistance; the model/data side had zero iterations, and the
   evaluator's inability to accept fenced JSON was never noticed.

## Keep / discard

Keep as-is: contracts (`FastModelOutput`, `DialogueAct`, `ReasonerRequest`);
the simulator (16 families × 2 configs, multi-turn environment, scripted
oracle, verifier); the Phase 02 Data Factory checks (provenance, licence,
PII, exact/semantic dedup, cross-split leakage, `normalized-trajectory-v1`
with teacher/provider/judge roles); the Phase 03A1 runner, artifact and
replay/tamper checks, r2 manifests and holdout splits, the hosted adapter;
the 03B detectors (`detect_pii`, `detect_disallowed_disclosure`,
`detect_false_completion`, `detect_unsupported_response_facts`); `qwen_mlx.py`
as a local smoke adapter only.

Discard or rewrite: the compact v2 prompt (restore the schema-embedding 03A1
prompt and state `reason_code ≤ 256` with short examples); `qlora-smoke.yaml`
and the 26-row lookup-labelled dataset; `_policy_violation` naming; bare
`json.loads` in `generate()` (report strict and fence-tolerant parsing
separately); training on a 4-bit base; MLX as the training platform.

## Recommended redo: verifier-filtered teacher distillation

The executable, stage-gated version of this section is the prepared contract
`harness/build/phase-03c-fast-model-distillation.md`.

**Teacher.** The outputs are structured decisions checked by a verifier. On
scripted single-turn scenarios the oracle already fixes `dialogue_act` and
`reasoner_request.needed`; a teacher cannot beat it there. Its value is in
`response_text` naturalness and diversity, short `reason_code` rationales,
`fact_updates` extraction from provider text, and multi-turn/rewritten states
the oracle does not cover. Caution: hosted models scored poorly on this
harness before the prompt-parity fix (r4 `frontier_reference_medium` 3/32
E2E; r5 5/6 after the fix), so **teacher samples must be rejection-sampled
against the oracle/verifier** — a sample whose act differs from the oracle is
dropped, not learned. Use decision fields from the oracle and text fields
from the teacher. Candidate teachers named by the project owner are Claude
Sonnet and Gemini Flash; a second family can serve as an agreement filter
rather than a second primary teacher. Exact model ids, availability, and
prices must be checked at execution time and are not recorded here.

**Data.** First parameterise scenarios in the Data Factory (current and
target totals, offer prices, features, fees, term, expiry, disclosure
requests) so instances differ while remaining verifier-checkable. Target
≈13 training families × 2 configs × ~100 instances ≈ 2.6k single-turn
prompts, plus 2–3 Fast decision points per multi-turn episode → 5–8k
candidates, 3–5k kept after filtering. Sample k = 2–4 per prompt at
temperature > 0; keep only if schema-valid → act/needed match the oracle →
verifier E2E passes → detectors pass → not a semantic duplicate. Record
teacher snapshot and cost in `GeneratorSnapshot`. Hold out the same three
test families as before, plus a provider-config holdout and an entity-cluster
holdout; draw dev from within training families by entity cluster so dev
targets are not a subset of train targets. Order-of-magnitude cost estimate:
≈24M input / 5M output teacher tokens, roughly USD 100 at typical hosted
prices (estimate, verify before running).

**Training.** One A100/H100 80 GB (bf16 LoRA at 2k sequence is comfortable
for 4B or 8B; full fine-tuning of 4B needs ~64 GB plus activations with
gradient checkpointing); an L4/A10 24 GB can run 4B LoRA 3–4× slower but
forces 4-bit QLoRA on 8B. After this review the user chose `Qwen/Qwen3-8B`
(hybrid thinking; force `enable_thinking=False`) — see the Phase 03C
contract. Framework: TRL
`SFTTrainer` + PEFT — native Qwen3 chat template, assistant-only loss, and a
merged export that loads directly into the planned vLLM path. LoRA r 32–64,
alpha 2r, all linear layers, on the official bf16 base; 2–3 epochs; LR
1e-4–2e-4 (full-FT 1e-5); cosine with 3% warmup; effective batch 16–32; seq
2048. Every ~100 steps run the real evaluator on dev and select the checkpoint
by act agreement / E2E, not by loss. ≈15M training tokens, under an hour on
an A100 for LoRA; GPU cost in the USD 5–20 range (estimate).

**Evaluation.** Report strict and fence-tolerant JSON parse rates separately,
schema validity, canonical compile, `dialogue_act` and `needed` agreement
with the oracle, multi-turn verifier E2E, false-completion, authority, PII,
disclosure, numeric grounding, latency and tokens. Arms: oracle ceiling;
untuned Qwen (bf16 official weights, fixed prompt); untuned Qwen + vLLM
guided JSON (separates format from decision); the teacher itself as Fast;
distilled Qwen with and without guided JSON. Held-out family n ≥ 100 per arm
for Wilson intervals; detecting a ~5-point improvement near p ≈ 0.5 needs
roughly ≥ 400 per arm. Six scenarios are a smoke, never a claim. Reuse
`runner_v2.py`, `artifacts_v2.py`, the r2 manifests and replay checks,
`openai_frontier.py`, the Data Factory checks, and the 03B detectors with
fence handling added.

## What the existing evidence can and cannot say

It cannot say that Qwen3-4B cannot learn this task, that QLoRA or MLX is
unsuitable, or that a larger model is required. It shows that the prompt
change broke the baseline, that ten LoRA updates did not change behaviour,
and that a strict parser scored two formatting issues as 0/6. The adapter is
lost, so Arm B cannot be re-scored with a tolerant parser. Teacher quality on
this harness is unknown until its verifier-filtered pass rate is measured on
held-out families.

A pre-registered Go/No-Go for the redo, at held-out n ≥ 100: (1) untuned Qwen
with the fixed prompt reaches ≥ 98% schema validity (03A1 already hit 32/32;
this is the floor); (2) the distilled model's act-agreement and E2E
improvement over untuned has a confidence interval excluding zero; (3) no
safety-detector regression. If (1) holds and untuned + guided JSON already
approaches the teacher, "prompt plus constrained decoding is sufficient, no
distillation needed" is a legitimate No-Go and should be recorded as such.
