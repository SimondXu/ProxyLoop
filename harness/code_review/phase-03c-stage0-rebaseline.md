# Phase 03C Stage 0 Re-baseline Review

**Target**: `feat/phase-03c-stage0-rebaseline` working tree against `main` at
`763a1a9` (stacked on `chore/docs-progress-sync` `524c69b`, PR #31)

**Reviewer**: independent read-only `reviewer` subagent (Claude Opus, high
effort, fresh context), invoked by the root orchestrator on the stable diff.

**Final recommendation**: Approve. No blocking findings; accepted findings
were applied by the root orchestrator before the gate and did not change
evaluator output on the committed rows, so re-review was not requested.

## Scope reviewed

- `fast_parse.py` strict/tolerant extraction and duplicate-key rejection,
  including adversarial inputs (nested fences, trailing prose, CRLF, BOM,
  `json` prefix without fence, `<think>` around valid JSON, empty body);
- `phase03c_experiment.py` evaluator semantics on the valid and invalid
  paths (`policy_violation` composite, `oracle_act_mismatch`,
  `thinking_leak`, `end_to_end_valid`);
- v3 prompt port: 03B text and compact view kept byte-for-byte, schema block
  and `reason_code` line added, no oracle/evaluator leakage,
  `enable_thinking=False` on the real MLX path for the 8B spec only;
- `qwen_spec.py` attestation against a tampered or wrong snapshot, and
  equality of the 4B spec with the historical adapter attestation;
- committed errata and smoke artifacts recomputed from source (aggregates,
  content fingerprints, prompt fingerprints against the current builder);
- scope: no training, hosted calls, semantic repair, or 03A1/03B artifact
  or test changes; `make test` fails closed when results are missing.

## Independent verification observed by the reviewer

`make phase03c-smoke-check`, `pytest ml/tests` (211 at review time, 220
after remediation), `make lint`, `make typecheck`, `git diff --check`,
`make phase03b-experiment-check`, `make hosted-rerun-check`; 17 frozen
03A1/03B SHA-256 values matched the log; `git diff --stat` on the frozen
files was empty. Errata aggregates and both smoke fingerprints reproduced.
8B pass bar (strict 6/6, schema 6/6, thinking leak 0/6) confirmed.

## Findings and resolutions

### Important — attempt-01 diagnostic mislabelled by location

The first 8B run (schema-only prompt) sat in `results/` with
`result_role="canonical"` and a v3 compiler version while its prompt
fingerprint did not match the v3 builder.

**Resolution**: moved to `data/experiments/phase-03c/diagnostics/`;
`check_smoke_results` now rejects any stray file under `results/`. The
file's own header is unchanged (rewriting would require re-signing); the
log states this explicitly.

### Important — log claimed idle status and a recorded review prematurely

**Resolution**: the log was finalized at the gate with the actual review
outcome and `harness/status.toml` returned to `idle`.

### Minor — `end_to_end_valid` did not exclude `duplicate_key`

Unreachable through `generate`, but the exported function is reused later.

**Resolution**: clause added; direct-call test added.

### Minor — `check_smoke_results` did not bind the checkpoint spec

**Resolution**: `controls.base_checkpoint` must equal the spec for the
file's model. Binding `evaluation_pipeline_fingerprint` was declined because
it would force a 16 GB model rerun on every source edit; the value is
recorded and matches the tree at this commit.

### Minor — missing tests

**Resolution**: adversarial parse cases, attestation round-trip and tamper
cases, and fail-closed tests for missing/stray/swapped results were added
(43 tests in `test_phase03c_experiment.py`).

### Noted, not changed

An orphan `</think>` without an opening tag is not flagged; in non-thinking
mode the open tag is the contract's signal. The appended system sentence also
restates the `reason_code` length; consistent with preflight decision 6.

## Contract deviation acknowledged by the reviewer

The root orchestrator's decision to leave `qwen_mlx.py` and `fast_output.py`
untouched (both are bound by the Phase 03A1 r4 execution contract, contrary
to the 03C contract and handoff text) and to implement the parser, spec, and
`generate` override in new modules was reviewed and found consistent with
the Stage 0 acceptance criteria.
