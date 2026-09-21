# Phase 03C Stage 0 Preflight

Date: 2026-09-21

This file separates observed repository state from the decisions frozen
before Stage 0 code work. It claims no smoke result; those live in
`harness/log/phase-03c-stage0-rebaseline.md` and the committed artifacts.

## Activation evidence

- The user activated Phase 03C Stage 0 on 2026-09-21 ("按照你的建议去做并且
  开始整个 flow") after the handoff in `harness/context/phase-03c-handoff.md`.
- `harness/status.toml` moved from `idle` to `in_progress`,
  `active_product_phase = "03C-stage0"`,
  `active_contract = "harness/build/phase-03c-fast-model-distillation.md"`.
- Integration baseline: `main` = `763a1a9` (Phase 07A). The branch
  `feat/phase-03c-stage0-rebaseline` is stacked on `chore/docs-progress-sync`
  (`524c69b`, PR #31) because the 03C contract and handoff are in that docs
  PR. It will be rebased onto `main` once #31 merges.
- PR #30 (`chore/claude-code-harness`) was open and green at activation; its
  12 files are present in this worktree as uncommitted, byte-identical copies
  and are not part of Stage 0.
- Local checks at activation: `make preflight-fast` passed;
  `git worktree prune` removed the dead UI worktree; merged branch
  `feat/phase-00b-contracts` (PR #2) deleted locally and on origin.

## Observed local model state

- `~/.cache/huggingface/hub/models--mlx-community--Qwen3-4B-Instruct-2507-4bit`
  snapshot `50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b` (2.1 GB) is the 03A1/03B
  base; it still attests against the historical fingerprints in `qwen_mlx.py`.
- `Qwen/Qwen3-8B-MLX-bf16` was downloaded during Stage 0 at revision
  `6766fd4b8101fa4201cc55c5a2e464f3d301f792` (13 files, 16.40 GB, four
  safetensors shards, chat template embedded in `tokenizer_config.json`,
  no `chat_template.jinja`). Hugging Face card license: `apache-2.0`.
  Source lineage `Qwen/Qwen3-8B` at `b968826d9c46dd6066d109eabc6255188de91218`
  (card license `apache-2.0`).
- Observed 8B snapshot fingerprints, pinned in `QWEN3_8B_BF16_SPEC`:
  checkpoint `9dc231054f911dfc2f83cdbacf1925ce0f86e15e22e42b369794c0a6668c80cd`,
  tokenizer `bc73b4d7e1c6615d001b2f9ed981d6f1393a6899b4294e264c2b3bbf3f3ab035`,
  chat template `57f1fd00f0013a2be96aa79b857391f27e23df5b5f847072b524c897e24d0361`
  (SHA-256 of the embedded template string).
- The 8B chat template contains the `enable_thinking` switch and `<think>`
  handling; `mlx-lm 0.31.3` / `mlx 0.32.1` are installed in `ml/.venv`.
- No 03B LoRA adapter exists locally; Arm B can only be re-scored from its
  stored `raw_output`.
- Machine: Apple M4 Pro, 48 GB unified memory, 407 GB free disk.

## Frozen decisions

1. Stage 0 base checkpoint is the official `Qwen/Qwen3-8B-MLX-bf16` export
   above, never a community quantised 8B. The 4B 4-bit base is run once more
   as a reference row only.
2. `enable_thinking=False` is passed on every chat render for the 8B spec
   (`QwenModelSpec.enable_thinking=False`); the 4B Instruct spec passes no
   switch so its historical prompt bytes and fingerprints are unchanged.
   Any `<think>` in raw output is recorded as `thinking_leak=True` and is an
   `invalid_output` failure, even when valid JSON follows it.
3. Parsing is dual-reported: `json_valid_strict` (raw text parses with no
   duplicate keys) and `json_valid_tolerant` (parses after stripping at most
   one markdown fence with an optional leading `json` word). The fence body
   is never edited; duplicate keys are rejected, not de-duplicated.
4. `policy_violation` in Phase 03C is the safety composite
   `disclosure_violation or authority_violation or false_completion or
   stale_pin_violation`. Disagreeing with the oracle's dialogue act is
   `oracle_act_mismatch`, a task metric.
5. Phase 03B bytes stay frozen: `phase03b_experiment.py`,
   `scripts/run_phase03b_smoke.py`, every file under
   `data/experiments/phase-03b-qlora-smoke/`, and every
   `data/evaluation/phase-03a1-*` artifact. Their SHA-256 list is recorded in
   the Stage 0 log.
   **Correction to the contract and handoff:** `qwen_mlx.py` and
   `fast_output.py` are *not* free to change. Both are bound by the Phase
   03A1 r4 execution contract (`hosted_rerun.py::_R4_EXECUTION_PATHS`), and
   editing them made `make hosted-rerun-check` fail with "r4 execution
   contract drift after Provider probe" during Stage 0. The dual parser
   therefore lives in the new `fast_parse.py`, the configurable checkpoint
   identity in the new `qwen_spec.py`, and `Phase03CQwenAdapter` overrides
   `generate` instead of the historical adapter changing. The contract's
   "change `test_qwen_mlx_adapter.py`" item is replaced by equivalent tests
   in `test_phase03c_experiment.py`; the historical test file is untouched.
6. The v3 prompt keeps the 03B compact view byte-for-byte and adds the
   embedded `FastModelOutput.model_json_schema()`, the `reason_code` line,
   and an explicit "no fence, no leading word, no repeated key" instruction.
   Version `phase-03c-fast-compiler-v3`.
7. Stage 0 pass bar (8B, six dev scenarios, greedy, 512 tokens):
   strict JSON >= 5/6, schema-valid >= 5/6, `thinking_leak` 0/6. It is
   evaluated and written into the result (`stage0_pass_bar`) but never
   enforced by the runner; the reviewer and the root orchestrator judge it.
8. No training, no hosted calls, no semantic output repair, no change to
   the `NO_GO_STOP_PHASE03B` text.
