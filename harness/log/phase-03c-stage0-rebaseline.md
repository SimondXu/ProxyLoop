# Phase 03C Stage 0 Re-baseline Execution Log

**Date**: 2026-09-21
**Baseline**: integrated `main` at `120e102` (Phase 07A + PR #30 harness +
PR #31 docs/03C contract). The work was done on
`feat/phase-03c-stage0-rebaseline` stacked on the #31 branch (PR #32, closed
when #31's branch was deleted at merge) and cherry-picked unchanged onto
`main` as `feat/phase-03c-stage0-rebaseline-v2`.
**Branch**: `feat/phase-03c-stage0-rebaseline-v2`
**Contract**: `harness/build/phase-03c-fast-model-distillation.md`, Stage 0
**Status**: Stage 0 code, offline errata, and both untuned smokes complete
locally; independent review Approve (below) with accepted findings applied;
`harness/status.toml` returned to `idle` at this gate. PR and CI pending at
the time of this pre-merge log. Stage 1 (hosted spend) and Stage 2 (cloud
GPU) remain unauthorized.

## Scope and non-goals

Scope: fix the evaluator's parsing, make the local Qwen checkpoint
configurable, port the schema-embedding prompt (v3), re-score the stored
Phase 03B raw outputs offline, and re-baseline untuned Qwen3-8B (plus a 4B
reference row) on the six frozen dev scenarios. USD 0, local only.

Non-goals held: no training, no hosted or teacher calls, no semantic output
repair, no change to the `NO_GO_STOP_PHASE03B` text, no 03A1/03B artifact
rewrite.

## Delivered

- `ml/evaluation/src/proxyloop_evaluation/fast_parse.py` (new):
  `extract_fast_json` (`strict` / `fenced` / `prefixed_fenced`, strips at most
  one fence and never edits the body), `parse_fast_json` with
  `DuplicateJSONKeyError`, `duplicate_json_keys`.
- `ml/evaluation/src/proxyloop_evaluation/qwen_spec.py` (new): `QwenModelSpec`,
  `QWEN3_4B_4BIT_SPEC` (reproduces the historical constants exactly),
  `QWEN3_8B_BF16_SPEC` (official MLX bf16 export, revision and file
  fingerprints pinned, `enable_thinking=False`, Apache-2.0),
  `observe_qwen_snapshot` (sharded weights, embedded chat template) and
  `attest_qwen_spec`.
- `ml/evaluation/src/proxyloop_evaluation/phase03c_experiment.py` (new):
  `Phase03CQwenAdapter` (v3 prompt = 03B text and compact view verbatim +
  embedded `FastModelOutput.model_json_schema()` + the `reason_code` line;
  spec-aware attestation; `enable_thinking` passed on every render; own
  `generate` with strict/tolerant parse, `thinking_leak`, new error codes
  `duplicate_json_key` / `invalid_json_after_fence_strip` / `thinking_leak`),
  `evaluate_fast_result_v3` (`oracle_act_mismatch` task metric;
  `policy_violation` = disclosure ∨ authority ∨ false completion ∨ stale pin),
  `derive_parser_erratum`, `check_parser_errata`, `check_smoke_results`.
- `scripts/run_phase03c_smoke.py`, `scripts/prepare_phase03c_errata.py`;
  Makefile targets `phase03c-errata` and `phase03c-smoke-check` (the latter is
  part of `make test`).
- `ml/tests/test_phase03c_experiment.py` (43 tests). No existing test file
  changed.
- Artifacts: `data/experiments/phase-03c/errata/phase-03b-arm-{a,b}-parser-erratum.json`,
  `data/experiments/phase-03c/results/arm-a-untuned-8b-v3.json`,
  `arm-a-untuned-4b-v3.json`; the diagnostic
  `data/experiments/phase-03c/diagnostics/arm-a-untuned-8b-v3-attempt-01-schema-only-prompt.json`
  (kept out of `results/`, which `check_smoke_results` now guards).
- `harness/context/phase-03c-preflight.md`; `harness/status.toml` activated
  for the phase and returned to idle at the gate.

## Deviation from the contract (root-orchestrator decision)

The contract and handoff state that `qwen_mlx.py` is free to change. It is
not: `qwen_mlx.py` and `fast_output.py` are bound by the Phase 03A1 r4
execution contract (`hosted_rerun.py::_R4_EXECUTION_PATHS`). The first
implementation edited both and `make hosted-rerun-check` failed with
"r4 execution contract drift after Provider probe". Rewriting the r4 report
is forbidden by the same contract, so the parsing helpers and checkpoint
identity were moved into the new `fast_parse.py` / `qwen_spec.py` and
`Phase03CQwenAdapter` overrides `generate` instead. Consequences: the
contract's "change `test_qwen_mlx_adapter.py`" item is replaced by equivalent
tests on the 03C adapter; the historical `QwenMLXAdapter` still rejects fenced
output (asserted by a test); `Phase03CQwenAdapter.__init__` sets the frozen
parents' private fields directly and documents why.

## Offline parser errata (zero model calls)

Source SHA-256: Arm A `b2a994d1eea6…`, Arm B `274e71e06f70…` (recorded in the
errata). Numbers match the contract's expectations and are asserted by tests:

| | strict parse | tolerant parse | duplicate key | schema valid | `reason_code` > 256 | dialogue act | oracle act mismatch |
|---|---|---|---|---|---|---|---|
| 03B Arm A (untuned 4B, v2 prompt) | 6/6 | 6/6 | 0/6 | 1/6 | 5 | `challenge` ×6 | 6/6 |
| 03B Arm B (QLoRA, v2 prompt) | 0/6 | 6/6 (`prefixed_fenced`) | 2/6 (`action_intent`) | 0/6 | 4 | `counter` ×6 | 6/6 |

New fact not in the contract: Arm B is schema-invalid 6/6 even after fence
stripping (4× over-long `reason_code`, 2× duplicate key), so tolerant parsing
alone would not have rescued the tuned arm.

## Untuned v3 smokes (six dev scenarios, greedy, seed 0, 512 tokens, MLX)

| model | strict JSON | schema valid | thinking leak | policy violation | oracle act mismatch | reasoner_request match | unsupported facts | median latency | prompt tokens max (26 rows ≤ 2048) | MLX peak |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3-8B bf16 (`arm-a-untuned-8b-v3.json`) | 6/6 | 6/6 | 0/6 | 0/6 | 6/6 | 4/6 | 0/6 | 8.3 s | 1408 | 17.0 GB |
| Qwen3-4B 4-bit reference (`arm-a-untuned-4b-v3.json`) | 6/6 | 6/6 | 0/6 | 0/6 | 6/6 | 0/6 | 1/6 | 3.8 s | 1404 | 3.2 GB |

- Stage 0 pass bar (8B): strict ≥ 5/6 ✔, schema ≥ 5/6 ✔, thinking leak 0 ✔.
  `stage0_pass_bar.all_pass = true` is written into the result but is
  descriptive; this log and the review are the judgement.
- Both models answer `challenge` on all six scenarios; the oracle expects
  `confirm` ×4 and `escalate` ×2. `end_to_end_valid` is therefore 0/6 for
  both. This is the honest untuned baseline Stage 0 exists to establish; it
  is not a Stage 0 failure and it is the gap Stage 1–3 are designed to test.
- Determinism: three runs of each model (before and after the parser code
  moved between modules, and after the review remediation) produced the same
  six raw outputs byte-for-byte (`raw_output_sha256`). The committed files are
  the last run, so their `evaluation_pipeline_fingerprint` matches the tree.
- Attempt 01 (`diagnostics/…-attempt-01-schema-only-prompt.json`, prompt
  fingerprint `13194d19…`; its `result_role` still reads `canonical` and its
  pipeline fingerprint predates the module move — it is a diagnostic by
  location and by this log, not by its own header): the system prompt
  replaced 03B's OUTPUT_SHAPE hint
  with the schema alone. Result: strict 6/6, schema 3/6 (all three failures:
  `fact_updates[].value` emitted as a list), `fact_updates` non-empty 6/6,
  but dialogue-act accuracy 5/6. Restoring the 03B text verbatim (contract
  wording "keeps … re-embeds") fixed format and dropped act accuracy to 0/6.
  Reviewer input: the untuned model's act choice is prompt-sensitive; Stage 3
  arms must hold the v3 prompt fixed and any prompt change is a new arm.
- The 8B model echoed the `reason_code` examples from the prompt line
  verbatim (`offer_candidate_requires_slow_review` ×4,
  `provider_state_requires_replan` ×2); the 4B invented codes. Noted for
  Stage 1 prompt-set design (example anchoring).

## Checks

Passed (local, this branch, final code, after review remediation):
- `make preflight` — exit 0: ruff format-check and lint (runtime + ML),
  mypy (57 + 35 files), runtime 291 passed / 33 guarded infra skips, ML 220
  passed (177 existing + 43 new), web eslint + vitest 47 passed, every
  artifact check including `phase03b-experiment-check` and the new
  `phase03c-smoke-check`, `check-layout`, `lock-check`,
  `docker compose config`.
- `make hosted-rerun-check` — "Phase 03A1-R r4 artifacts valid (ready)"
  after the module move (it failed before it; see Deviation).
- `git diff --check` — clean.
- SHA-256 of all 17 Phase 03A1/03B artifacts unchanged (list below).

Not run / not applicable:
- `postgres-check`, `phase05a-check`, `phase06b1-check` — need the Compose
  profiles; nothing in Stage 0 touches those paths.
- Browser checks — no UI change.
- Hosted, cloud, GPU, training — out of Stage 0 scope by contract.

## 03A1/03B artifact SHA-256 (unchanged before and after Stage 0)

- `data/evaluation/phase-03a1-baselines-report.json` `759a45263fdefd3a1c85cce38acbe29e1906f79a1db375266643d3b08ac842fb`
- `data/evaluation/phase-03a1-r2-baselines-report.json` `dbfb88c72317046b587ca63142adf71cf0f9b27d4b8f6bcb56e071bf290506b3`
- `data/evaluation/phase-03a1-r3-baselines-report.json` `c5ed4955bf598db2807a30aa1795fdf886f5b2cf6de2d27ec17541dc10bbcd72`
- `data/evaluation/phase-03a1-r4-attempt-01-auth-misconfigured.json` `633e4121e0adfd95e37ed678af4368f20331e6af6d2c2fca1542b8bf3b67726d`
- `data/evaluation/phase-03a1-r4-attempt-02-unsupported-schema.json` `e4735b496bfdad6f04c460be1c998b1f04732af946d99e95ad5d7299e2df8e34`
- `data/evaluation/phase-03a1-r4-hosted-rerun-report.json` `d051a830e05ee193da9118978fc32d7eacae582b6422b4e01c65ed0af9e40827`
- `data/evaluation/phase-03a1-r5-validity-smoke-report.json` `2fec386cdc962c2a612a0d8eabe43ee8f3e2f038f2da1a52ac87c9a40b602107`
- `data/experiments/phase-03b-qlora-smoke/manifest.json` `2ae744cb085ef39b97da34baa58f965de553b01aea6f807dd59975f19dea6e1b`
- `data/experiments/phase-03b-qlora-smoke/qlora-smoke.yaml` `f8a08e9cf8ecc873a305baf748a827d3e416921349ad12253ac98e1872a6b9fb`
- `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned-detector-diagnostic.json` `2a6929c809d3ccd701b1adbae58b08d4fedd1f79d6e616c64a9b8070b7168b63`
- `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned-pre-provenance.json` `636c1f865eba822a35519c8700594d9c4dc4c7fd686cb719a331c029c9b537a5`
- `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned-pre-remediation.json` `bd76473852ff8a8c7af5d506bc978281cb42fd0aed58940760dccb5ecb7e2a7d`
- `data/experiments/phase-03b-qlora-smoke/results/arm-a-untuned.json` `b2a994d1eea6989cadbcf9873d8c7bdc7722ed0b4764807fd1245c4a87d3b0f0`
- `data/experiments/phase-03b-qlora-smoke/results/arm-b-qlora.json` `274e71e06f708d70a66bc6c30a148cab283b27350f62d4862339d838d8036f36`
- `data/experiments/phase-03b-qlora-smoke/results/comparison.md` `fde9ebefaa939dd49a3bc56b0efa105144f1cfce73b047df0dc3eb2002088945`
- `data/experiments/phase-03b-qlora-smoke/train.jsonl` `950c3ccf8e313b520b2f99286752dd5314e33ab011feea236bdfb69624159e28`
- `data/experiments/phase-03b-qlora-smoke/valid.jsonl` `6f229cfdd8136bc17939522fe18d38dc3eb4fd3553238d5235226dbd47bfe20a`

## Independent review

Reviewer role (`.claude/agents/reviewer.md`, Opus, high effort, fresh
context, read-only) on the stable diff; it re-ran `phase03c-smoke-check`,
the 03C tests, lint, typecheck, `phase03b-experiment-check`,
`hosted-rerun-check`, recomputed both errata aggregates, both results'
content fingerprints, prompt fingerprints against the v3 builder, and the 17
frozen SHAs. Recommendation: **Approve**; no blocking findings.

Accepted and applied before this gate:
- Important 1 — the attempt-01 result sat in `results/` with a `canonical`
  header. Moved to `diagnostics/`; `check_smoke_results` now fails on any
  stray file in `results/`.
- Important 2 — this log claimed idle status and a recorded review before
  either was true. Corrected at the gate (this version).
- Minor 3 — `evaluate_fast_result_v3` now includes `not duplicate_key` in
  `end_to_end_valid` (previously unreachable through `generate`, but the
  function is exported and Stage 3 will reuse it); test added.
- Minor 4 (first half) — `check_smoke_results` binds `controls.base_checkpoint`
  to the spec named by the file. The second half (binding
  `evaluation_pipeline_fingerprint`) was not adopted: it would force a
  16 GB model rerun for every comment-level edit; the fingerprint is recorded
  in the file and matches the tree at this commit.
- Minor 5 / 8 and G — adversarial parse cases (CRLF, empty body, fence inside
  a JSON string, BOM, prose after fence, `json` prefix without fence),
  attestation round-trip and tamper tests, and fail-closed tests for
  missing/stray results and a swapped `base_checkpoint` were added.

Not adopted: Minor 6 (an orphan `</think>` is not flagged) — in non-thinking
mode the model never opens a think block, and the open tag is the signal the
contract names; recorded as a known limit. Minor 7 is a note, no change.

After remediation the smokes were rerun (identical raw outputs) and
`make preflight` passed again (see Checks); no semantic change to evaluator
output on the committed rows, so re-review was not requested.
