# PR-9b (first half): local distilled Fast gateway and M1 stack parity

Branch `feat/pr9b-local-fast-gateway` from `origin/main` @ `1573a42`.
Frozen spec: `harness/context/pr9-local-distilled-fast-design.md` (root
answers Q1–Q12; this change is the 9b part that does not need 9a's runtime
seam).

## Scope

In: the PEFT → MLX adapter converter and its committed hash attestation
(`ml/serving/`); the silent-load guard; the loopback gateway under
`proxyloop_evaluation/local_fast/` (the 03C v6 path, stdlib wire, identity);
a CI-usable fake (`LocalFastGatewayCore.with_generator`, the real core and
HTTP layer with an injected generator, no MLX); the M1 parity run over the
240 cloud held-out rows with the pre-registered bar; the parity report with
per-row outputs (Q7) and `make phase03c-local-parity-check` in `make test`.

Not in (no frozen or hot file touched): `qwen_mlx.py`, `fast_output.py`,
`ml/pyproject.toml`, `ml/uv.lock`, `runtime/`, `apps/`, every `agent_core`
file. No download (`HF_HUB_OFFLINE=1`), no hosted call, no credential, no
network except 127.0.0.1.

## Status of the first-half pending list

Everything the first half deferred until PR-9a landed is done on this branch:
the M2 run, the gate pass rate, the local split reports, the switch to the
shared wire module (the interim `local_fast/wire.py` is deleted) with the 9a
golden fixtures checked from the ml side, the docs, and the Browser check. See
the sections from "Second half after PR-9a" on.

## Local inputs (redacted)

- PEFT adapter: `<main checkout>/data/experiments/phase-03c/training/cloud-run-01/train/adapter/`
  (git-ignored; the worktree has only the committed `adapter_config.json`).
  `adapter_model.safetensors` sha256 `61c29e19…4e84f22` = the run manifest's
  `adapter_sha256`; 504 F32 tensors = 36 layers × 7 modules × (A, B), so the
  expected LoRA layer count is 252, as the spec says.
- Base: `~/.cache/huggingface/hub/models--Qwen--Qwen3-8B-MLX-bf16/snapshots/6766fd4b8101fa4201cc55c5a2e464f3d301f792`
  (already cached; attested by `attest_qwen_spec` at every load).
- Converted MLX adapter: the worktree's ignored
  `data/experiments/phase-03c/training/cloud-run-01/train/mlx/adapters/`.
- Host: Apple M4 Pro, 48 GiB (`hw.memsize` 51539607552), macOS 26.5.1,
  Python 3.12.10, `mlx` 0.32.1, `mlx-lm` 0.31.3.
- `uv sync --project ml --extra evaluation --offline` from the uv cache; a
  plain `uv run --project ml` keeps `mlx-lm` (spec R11 verified).

## Converter and attestation

- `python -m scripts.convert_phase03c_adapter_mlx --source <PEFT dir> --write-attestation`:
  1.4 s; wrote `ml/serving/phase-03c-cloud-run-01-mlx-attestation.json`
  (content fingerprint `73f38d00…97d24b19`, 36 layers, 252 LoRA layers, 504
  tensors, rank 32, alpha 64, scale 2.0). A second run without
  `--write-attestation` printed `matches`.
- Deviation from the spec wording "pure `mlx.core`": the converter is
  standard-library only (safetensors read/transpose/write), for the same
  reason (no new dependency) and so CI, which has no MLX, runs it. An
  independent MLX cross-check (`mx.load` on both files): all 504 tensors are
  exact transposes of the PEFT tensors, and 252 `lora_b` are non-zero.
- Tests: `ml/tests/test_mlx_adapter_conversion.py` (G2, G5, and the committed
  attestation vs the run manifest): 10 passed.

## Silent-load guard

- Red first: `ml/tests/test_local_fast_gateway.py` guard tests failed at
  collection (`ModuleNotFoundError: proxyloop_evaluation.local_fast.gateway_core`),
  then 5 passed. The fake loader reproduces `strict=False` (unmatched names
  are ignored, `lora_b` stays zero); renamed layers, one unloaded layer, a
  wrong count, and LoRA layers on the untuned backend are refused.
- Real MLX, scratch copy of the converted adapter with `model.layers.` renamed
  to `model.layer.`: `mlx_lm.load returned without error in 9.2s`,
  `lora modules created: 252 with non-zero lora_b: 0`, `guard refused: 252 of
  252 LoRA layers have all-zero lora_b`. This is the hazard the guard exists
  for; the module paths matched the attested set exactly.
- Every real distilled load in M1 and in the live gateway passed the guard
  (252 layers, all non-zero).

## Gateway

- `ml/tests/test_local_fast_gateway.py`: 27 passed (G1 product-path prompt
  byte-identical to the trained prompt for both positions; core statuses and
  allow-listed detail codes; G4 loopback-only bind, 256 KiB cap (413 without
  reading the body), 400 on malformed/duplicate-key/wrong-version/deeply
  nested/mismatched-revision requests, 503 while busy with `/v1/identity`
  still answering, content-free 500 and logs).
- Live defect found and fixed: the first live run started (attestation and
  guard passed, `/v1/identity` 200) but `decide` returned `500
  gateway_error`, `model_error=generation_error`. Root cause, reproduced
  in-process: MLX streams are thread-local and the first generation on a
  fresh `ThreadingHTTPServer` handler thread fails with `There is no
  Stream(cpu, 0) in current thread.` (M1 was unaffected: it loaded and
  generated on the main thread.) Fix `f148362`: the core owns a one-worker
  executor for load, the self-check and every decide; red test
  `test_generation_runs_on_one_model_thread_whatever_thread_calls` failed
  with `assert 4 == 1` before the fix.
- Live smoke after the fix (distilled, port 18765, scratch
  `gateway_smoke.sh`): refuses to start without `HF_HUB_OFFLINE=1` and on host
  `0.0.0.0`; `GET /v1/identity` 200 (`identity_fingerprint c83bdd6b…`); one
  product-shaped `POST /v1/fast/decide` (prose Provider event plus the
  observation) returned `succeeded`, act `escalate` (= oracle), with the
  output and the input/output token counts identical to the M1 row for
  `refusal-transfer@1.0::retention-gated-v1@1.0::p950::pos1`; 14.9 s, then
  11.7 s for a repeat. The server log carried status, latency and token
  counts only.

## M1 stack parity (manual model lane)

Command: `bash scratchpad/impl-pr9b/m1-run.sh` (for each of distilled and
untuned, `HF_HUB_OFFLINE=1 uv run --project ml python -m
scripts.run_phase03c_local_parity --run --backend <b> --model-path <base>`),
then `--write`. Sequential, one model at a time, resumable JSONL under the
ignored `data/experiments/phase-03c/local-parity/runs/`.

- Wall time: distilled 2 smoke rows (1 min 14 s including load), then
  238 rows 11:01:32 → 12:18:11 UTC (76 min 39 s); untuned 240 rows
  12:18:11 → 12:58:50 UTC (40 min 39 s). Loads: 13.3 s / 12.0 s.
- Interruption note: the coordinator reported a rate-limit interruption at
  41/240. The run was not interrupted: the background job exited `rc=0`
  after both arms, and both JSONL files hold 240 rows. The runner resumes
  from partial files (identity-checked), which the 2 smoke rows used.
- Identities: distilled `c83bdd6ba873cb8f…`, untuned `39aa5f20b5383c46…`.

| | distilled (local) | cloud A3 | untuned (local) | cloud A1 |
|---|---|---|---|---|
| act agreement vs oracle | **236/240 = 0.983** (Wilson 0.958–0.994) | 236/240 | 133/240 = 0.554 | 130/240 = 0.542 |
| act concordance with cloud | **240/240 = 1.000** (Wilson 0.984–1.000) | — | 237/240 = 0.988 | — |
| raw output byte-identical to cloud | 136/240 | — | 192/240 | — |
| templated input tokens equal to cloud | 240/240 | — | 240/240 | — |
| prompt fingerprint equal to the bundle row | 240/240 | — | 240/240 | — |
| status | 240 succeeded | | 240 succeeded | |
| schema valid / policy violations / false completions | 240 / 0 / 0 | | 240 / 0 / 0 | |
| acts | confirm 124, counter 76, escalate 40 (= A3) | | counter 179, escalate 40, confirm 17, challenge 4 | |
| generation ms p50 / max | 21,312 / 26,884 | | 9,912 / 13,097 | |
| output tokens p50 / p95 | 193 / 220 | | 79 / 108 | |

**Verdict: stack parity held** (pre-registered bar: distilled act
agreement ≥ 0.95 and cloud concordance ≥ 0.95, point rates). Not a
silent load: the distilled arm reproduces A3's act distribution and
per-family pattern (required-feature-loss 36/40, all others 40/40), far
from the untuned numbers. The clustering note applies: 6 decision rules
carry the 240 rows, so the Wilson intervals are optimistic.

Latency (descriptive, one machine, sequential; other work ran on the machine
during the distilled arm): 134/240 distilled generations exceeded 20 s and
15/240 exceeded 25 s. The spec's estimate was 10–16 s (§2.7, [I]). Under the
spec's default `PROXYLOOP_FAST_TIMEOUT_S` 20, most distilled calls would end
as `fast_adapter_timeout`. Root decision after the review: PR-9a's default is
25 s (the cap). Consequence recorded here and in `ml/serving/README.md`: MLX
cannot cancel a generation, so after a client timeout the gateway stays busy
until that generation ends and the next Fast call in that window gets
`503 busy` and falls back.

Report: `data/experiments/phase-03c/local-parity/parity-report.json`
(1.1 MB; the 03C precedent `heldout-report.json` is 2.4 MB; no paths,
credentials or teacher text). `make phase03c-local-parity-check` passes
(12 s); after replacing one raw output's act in a working copy it failed
with `parity-report.json is stale or was edited` (then restored with git).
`ml/tests/test_local_parity.py`: 10 passed.

## Repository gates (on `6607165`)

- `make lint`: passed. `make typecheck`: passed (runtime 67, ml 70 source
  files).
- `make test`: passed (runtime 1294 passed, 59 skipped DB/Temporal-gated;
  ml 445 passed; every `*-check` passed, including `phase03c-rescore-check`,
  `phase03c-smoke-check`, `hosted-rerun-check` and the new
  `phase03c-local-parity-check`).
- `make preflight`: passed (format-check, lint, typecheck, test,
  check-layout, web-check with 140 web tests and the build, `lock-check`
  with `ml/uv.lock` unchanged, gated skips matching the pin of 59). No
  `PROXYLOOP_TEST_*` variable was set; the DB lane is not needed (no service
  change).
- Frozen and hot paths: `git diff 1573a42 -- ml/pyproject.toml ml/uv.lock
  …/qwen_mlx.py …/fast_output.py runtime apps` is empty.
- Not run: independent review (root's call), the DB/Temporal gates (not
  applicable), the Browser check (pending with 9a).

## Review remediation (review: Request Changes, no Blocking)

Review artifact: `harness/code_review/feat-pr9b-local-fast-gateway.md`.

- I1: `--write` and `--check` now run `validate_observed` first: each arm
  must hold exactly the cloud arm's prompt ids in cloud order, and its
  identity must equal `GatewayIdentity(backend, attested adapter fingerprint,
  recorded mlx_versions)` including `identity_fingerprint` (and agree with the
  host's MLX versions). Tests fail on dropped wrong rows (the reviewer's
  236/236 forgery, also through `main(["--check"])`), duplicated rows,
  reordered rows, a zeroed `decoding_fingerprint`, a swapped label, and an
  edit with a re-computed fingerprint. The integrity limits are stated in the
  report's `claim_boundary` and the README.
- M1: after load, the gateway fingerprints every loaded `lora_a`/`lora_b` with
  the attestation formula and requires the committed `content_fingerprint`
  (`check_loaded_lora_weights`). This compares memory against the committed
  hash instead of re-reading `adapters.safetensors`: a re-read would see the
  same swapped file as the load, so only this closes the verify/load gap.
  Real MLX: the attested adapter loaded with both checks in 12.1 s; a copy
  with only `model.layers.7.mlp.up_proj.lora_a` renamed passed the layer
  guard (252 layers, all `lora_b` non-zero) and was refused by the weight
  check. CI tests: partial load and file-changed-after-verify.
- M2 (code state of the M1 run). Distilled arm: started 11:01:32 UTC at
  `5429076` with the PR-9b code uncommitted (first code commits `6d5ed75`,
  `afeec4d` at 11:07 UTC). Untuned arm: started 12:18:11 UTC at `afeec4d`
  with `parity.py` and the runner uncommitted (committed unchanged in
  `1e74da0`). Both runs predate `f148362` (same calls, moved onto one
  dedicated thread). Per the session record, the distilled arm's uncommitted
  generation-path files differ from their first commits only by `ruff
  format`, the runner's import mechanics, and a `RecursionError` catch in
  `wire.py` (imported only for its version constant). The raw pre-commit
  bytes were not kept, so that is not byte-verifiable. **Finding: the
  generation path is byte-identical in behaviour.** Evidence:
  `prompt_fingerprint_matches` 240/240 against the bundle rows (prompt
  building); the frozen 03C decoding and parsing modules are base-commit bytes
  (the frozen-path diff is empty); at `31edadb` with a clean tree,
  `m2_replay.py` regenerated 10 distilled rows (the first of each family plus
  all 4 oracle-disagreeing rows) and 6 untuned rows with byte-identical
  `raw_output`, input/output token counts and prompt fingerprints, and both
  identities equal to the report's. (The untuned replay process started with
  uncommitted edits only in files it does not import: the runner,
  `http_server.py`, tests.) No rerun needed. Each arm's `code_state` in the
  report records this; future runs capture `head` and `dirty_paths` in the
  run header automatically. The rule "two unparseable outputs count as
  concordant" was written after the run; `both_unparseable_rows` is 0 in
  both arms, so it decided no row.
- M3: `--run` refuses without `HF_HUB_OFFLINE=1`
  (`set HF_HUB_OFFLINE=1: the parity run never downloads`).
- M4: every request needs `Host: 127.0.0.1:<port>` (400 `host_not_allowed`
  otherwise, including `localhost:<port>`: the PR-9a client must use
  `127.0.0.1`), decide calls need `Content-Type: application/json` (415), and
  socket reads time out after 10 s (408 `request_timeout`). Tests for each.
- M5: `test_load_and_decide_run_on_the_same_model_thread` drives the real
  `load` path with recording stand-ins for the MLX calls; construction,
  `_load_mlx` and both generations (direct and HTTP) run on one
  `local-fast-model` thread, not the caller's.
- M6: `render_mlx_config` derives the MLX config from the committed PEFT
  `adapter_config.json`; a test recomputes the attested `config_sha256`.
  The real conversion still reproduces the committed attestation (`matches`).
- M7: the README and the log state that the distilled latency was measured
  while other work ran on the machine.

Evidence scripts (scratch, not committed): `scratchpad/impl-pr9b/m2_replay.py`
(M2 replay), `real_weight_check.py` (M1 real-MLX partial load),
`m1-code-state.json` (the `--code-state` input to `--write`).

## Gates after the remediation and the `origin/main` merge (`b950011`, main @ `04a8ed5`)

- Merge conflicts: `Makefile` (both sides' targets kept: `fast-slow-split-check`
  from PR-8a next to `phase03c-local-parity-check`) and the status file (main's
  rows and the PR-9b row kept).
- `make lint`: passed. `make typecheck`: passed (runtime 70, ml 70 source files).
- `make test`: passed (runtime 1470 passed, 63 gated skips; ml 468 passed;
  every `*-check` passed, including `phase03c-local-parity-check` (stack parity
  held) and PR-8a's `fast-slow-split-check`).
- `make preflight`: passed (web 189 tests and build, `lock-check` with
  `ml/uv.lock` unchanged, gated skips matching the pin of 63).
- `git diff origin/main -- ml/pyproject.toml ml/uv.lock …/qwen_mlx.py
  …/fast_output.py runtime apps` is empty. No `PROXYLOOP_TEST_*` set.

## Second half after PR-9a (#97, main @ `a8fdf5b`): checkpoint 2026-09-24

The session paused at a usage limit. This section is the exact state.

### Done

- Merged `origin/main` @ `a8fdf5b` (`2e3ba11`): the spec takes main's copy
  (9a's plus the dated 25 s amendment); the status file keeps both rows.
- Shared wire (`167b605`): `local_fast/wire.py` deleted; the gateway uses
  `proxyloop_agent_core.local_fast_wire` (`DecideResponse`,
  `encode_decide_response`, the detail allow-lists). The fake identities encode
  to the 9a identity goldens byte-for-byte, a core result encodes to each
  response golden, the request golden is served, and the frozen
  `FastModelOutput` schema equals the golden once `description` is dropped.
- Host header: the 9a client accepts `127.0.0.1`, `::1` and `localhost`; the
  gateway binds IPv4 127.0.0.1 only, so it accepts exactly `127.0.0.1:<port>`
  and `localhost:<port>` (what `http.client` sends for those URLs); `[::1]`
  cannot reach the socket and every other name is refused. End-to-end tests
  (`ml/tests/test_local_fast_wire_compat.py`): the real 9a
  `LocalFastHttpAdapter` (runtime env, subprocess) against the real gateway
  HTTP server with a fake generator gets a line over both hosts, a typed
  `fast_adapter_invalid_output`/`invalid_json` failure, and a startup refusal
  for another backend.
- M2 script `scripts/run_phase03c_product_parity.py` (`5dc5ece`) and the
  split-report extension (`a19aa0e`, see below).
- **M2 manual run: complete.** Command: `scratchpad/impl-pr9b/m2-run.sh`
  (`HF_HUB_OFFLINE=1 … run_phase03c_product_parity --run --backend <b>`), then
  `--write`. Apple M4 Pro, 48 GiB, macOS 26.5.1, mlx 0.32.1, mlx-lm 0.31.3.
  Distilled: 200/200 generated rows, 14:41:02 → 16:00:51 UTC (79 min 49 s,
  load 22.1 s), run from `5dc5ece`, clean tree. Untuned: 200/200,
  16:00:51 → 16:36:27 UTC (35 min 36 s, load 12.5 s), run from `a19aa0e`
  (the commits after `5dc5ece` touch only the Makefile, the split script and a
  runtime test, none on the generation path) with the untracked
  `ml/tests/test_product_parity.py`. Both `rc=0`. Committed:
  `data/experiments/phase-03c/local-parity/product-path-report.json`;
  `make phase03c-product-parity-check` passes; `ml/tests/test_product_parity.py`
  13 passed.

### M2 results (240 held-out rows, product rendering path)

- Deterministic: 40/240 rows (all of refusal-transfer) are refused by
  `fast_public_observation` (`fast_observation_offer_missing`: the family has
  no offer), so the model is never called and the fallback is delivered. The
  other 200 rows all lose `applied_changes` (D4) and differ in offer ids (not
  in the prompt), so no product prompt equals its trained prompt and every
  row was generated. D3 (Provider-state defaults) changed no held-out row:
  their true flags are the defaults. Renderer information loss alone: the
  oracle's act on the product observation equals the true one on 120/240
  rows (promotion-credit confirm → counter and unsupported-action counter →
  confirm once the applied change is gone; refusal-transfer refused).
- Act agreement with the true oracle: distilled 157/240 (0.654) vs 236/240 on
  the trained path (M1); untuned 97/240 vs 133/240. Against the oracle of the
  product observation: distilled 157/240, untuned 87/240. Per family
  (distilled, true oracle, M1 → M2; corrected after the second-half review,
  I1): refusal-transfer 40 → 0 (no offer, refused before the model, not D4),
  unsupported-action 40 → 0 (D4: the model answers confirm, which follows the
  product input, 40/40 against the product oracle), required-feature-loss
  36 → 37, and promotion-credit 40 → 40 (the model keeps confirm although D4
  changes the product oracle to counter: 0/40 against the product oracle).
  D4 is about half of the drop (40 of the 80 lost rows), not the main cause.
- **Headline (Q1): delivered distilled lines through the product path: 0/240.**
  All 200 outputs that reach the gate are withheld by `fast-gate-v1`
  (`fast_gate_dialogue_act` 200, `fast_gate_number_not_allowed` 200,
  `fast_gate_completion` 181, `fast_gate_non_ascii_text` 72,
  `fast_gate_text_too_long` 47); the other 40 are refused before the model.
  Untuned: 8/240 delivered (192 gate-rejected: dialogue act and numbers).
  On the trained path (M1 outputs, trained snapshots) the gate passes 0/240
  distilled and 44/240 untuned, matching the spec's probe P4 estimate.
  No output failed compilation, `validate_fast_result` or the no-fact-updates
  rule. A negative result, recorded as such.
- Latency, descriptive: distilled product-path generation p50 23.9 s, max
  32.5 s; untuned p50 10.4 s, max 12.9 s.

### Local split reports (manual model lane, 2026-09-24)

- Command: `scratchpad/impl-pr9b2/split-run.sh` (the earlier runner, `PORT`
  8775 because 8765 was taken): for each backend, `HF_HUB_OFFLINE=1 uv run
  --project ml --offline python -m scripts.run_local_fast_gateway --backend <b>
  --model-path <base> --port 8775`, wait for `serving backend=`, then
  `run_fast_slow_split_report.py --write --fast-backend <b> --gateway-url
  http://127.0.0.1:8775` (default timeout 25 s), then stop the gateway. Run
  from `ab4f239` with a clean tree. Host as above.
- Wall time: distilled 23:07:53 → 23:11:09 UTC (gateway ready in 18 s),
  untuned 23:11:09 → 23:12:55 UTC (ready in 14 s); both `rc=0`. Identities:
  distilled `c83bdd6ba873cb8f…`, untuned `39aa5f20b5383c46…` (equal to M1).
- Result, both backends: turn structure equals the scripted replay (demo:
  slow_only 1, fast_only 1; dialogue: slow_only 1, fast_only 5,
  slow_then_fast 2). All 8 Fast calls per backend were gateway `succeeded`
  and gate-rejected, so every Fast turn delivered the fallback:
  `fast_model_line_rate` 0.0, `fallback_cause` gate 8 / failure 0, no
  timeout and no `busy`. Gate codes: distilled `fast_gate_completion`,
  `fast_gate_dialogue_act`, `fast_gate_number_not_allowed` on every call;
  untuned the last two. Fast call ms: distilled 21,039–24,106 (dialogue
  p50 22,084), untuned 10,435–12,131. Every call had the same token counts
  (1869 in; 184 out distilled, 78 out untuned), consistent with D5: the
  product prompt does not carry the consumer's words, so these scenarios
  give the model the same input each turn.
- `data/evaluation/fast-slow-split-scripted.json` sha256 `8d720f88…6bc02e`
  before and after (unchanged). `make fast-slow-split-check` passes.
  Committed in `9e3538a`.

### Docs

- `ml/serving/README.md`: M2 section (negative product result, Q1), local
  split reports section, M2 and split steps, the stale interim-wire paragraph
  replaced. `docs/architecture.md`: a measured paragraph in "Local opt-in
  Fast backend (PR-9a)". Status row updated. (`ac3135d`.)
- M2 detail added while writing the docs: 64 of the 200 distilled
  product-path generations took longer than 25 s (M1: 15/240), under
  uncontrolled machine load.

### Merge and gates (`7e6c1ce`, main @ `e10443d`, #98 PR-11)

- Conflicts: `docs/architecture.md` (the PR-9b paragraph kept before PR-11's
  "Local Fast backend under Temporal") and the status file (the PR-9b and
  PR-11 rows both kept). The `Makefile` auto-merged; `make test` still runs
  `phase03c-local-parity-check`, `phase03c-product-parity-check` and
  `fast-slow-split-check`.
- `make lint`: passed. `make typecheck`: passed (runtime 75, ml 70 source
  files). `make test`: passed (runtime 1624 passed, 66 gated skips; ml 494
  passed; every `*-check` passed, including M1 `stack parity held`, the
  product-path report, and the three split reports). `make preflight`:
  passed (format-check, lint, typecheck, test, layout, web 189 tests and the
  build, lock-check with `ml/uv.lock` unchanged, gated skips matching the pin
  of 66). No `PROXYLOOP_TEST_*` variable was set; no DB lane (no service
  change on this branch).
- `git diff origin/main -- ml/pyproject.toml ml/uv.lock …/qwen_mlx.py
  …/fast_output.py` is empty; no weights, adapters or converted files are
  tracked.

### Root decisions after the gates (`e85a75d`)

- `docs/ml-evidence.md`: the Phase 03C row and the held-out results now say
  the 98.3% is act agreement on the trained prompt path. They point to the M2
  negative product result: 0/240 delivered, 0.654 product-path act
  agreement, a link to the README M2 section.
- `make local-fast-gateway` takes `PORT` (default 8765), documented in
  `ml/serving/README.md` step 4. `make -n local-fast-gateway PORT=8775` ends in
  `--port 8775`; the Browser check below started the gateway through it with
  `PORT=8776`. `make check-layout` and `git diff --check` clean. (Renamed
  `LOCAL_FAST_PORT` after the second-half review; see below.)

### Browser check (spec §6.7 step 4, DB/Compose lane held by this branch)

Headless Chromium via Python Playwright at 1440x1000. Throwaway Compose
project `proxyloop-pr9b-browser` (postgres only, port 55473, fresh volume).
Distilled gateway started by `make local-fast-gateway BACKEND=distilled
PORT=8776` (identity `c83bdd6b…`). Runtime `proxyloop_api.server --mode
scripted` on 8021 with `PROXYLOOP_STORAGE_MODE=postgres`,
`PROXYLOOP_ORCHESTRATION_MODE=direct`, `PROXYLOOP_FAST_BACKEND=distilled`,
`PROXYLOOP_FAST_GATEWAY_URL=http://127.0.0.1:8776`, no model credentials.
Readiness: `{"ready":true,"dependency":"postgres","adapter_mode":"local_distilled_candidate","storage_mode":"postgres","orchestration_mode":"direct"}`.
Web: `next start` on 3021, the production build of `7e6c1ce` (`apps/web`
unchanged since `04a8ed5`). Its `/api/runtime` rewrite targets 8000 (taken),
so Playwright forwarded `/api/runtime/**` to 8021, as in the PR-8b and PR-10
checks. Scratch launcher and script: `scratchpad/impl-pr9b2/browser-launch.sh`,
`browser_check.py`.

- Flow: intake $92 / $75 / yes / yes, Create fictional Case, then "Keep
  both unchanged and continue" (the first consumer turn, one Fast call).
- After the first consumer turn: the one Assistant Message is the fallback
  line "I am checking that and will update you." with the automated-message
  label once. `POST /cases/{id}/events` took 23,389 ms, click to line
  23,456 ms. Status Bar: "Waiting for your approval of the exact terms.", as
  of Case revision 4, phase Awaiting Approval, approval Pending with its
  expiry, execution Not started. The Fast trace in the log table is
  `rejected` with `fast_gate_completion`, `fast_gate_dialogue_act`,
  `fast_gate_number_not_allowed`, model version `distilled:c83bdd6ba873cb8f`,
  latency 23,326 ms, tokens 1876 in / 184 out. The gateway said `succeeded`,
  the gate withheld the text, and the fallback was delivered, as M2 and the
  split reports predict. No console errors or warnings.
- **After reload the Web does not restore the Case.** It shows "Blocked ·
  Runtime state not verified: Recovery requires the durable
  Temporal/PostgreSQL/scripted Runtime profile. The direct Runtime makes no
  restart-recovery claim." The Status Bar is not rendered. Only
  `GET /health/ready` was called. This is the Web's designed fail-closed rule
  (`conversation-workspace.tsx`, the readiness check before restore): it
  restores only when readiness is temporal + postgres + `adapter_mode`
  `scripted`. So a Case on a local Fast backend is never restored after a
  reload, in direct mode or under Temporal. The rule is documented in
  `docs/architecture.md` ("makes no recovery claim for any value but
  `scripted`"). It is not a PR-9b defect, and no code was changed. The Case
  itself was durable: `GET /cases/{id}` on the Runtime after the reload
  returned revision 4 with the visible events provider_offer,
  consumer_message and the `assistant_message` "I am checking that and will
  update you." (no `fast` key).
- Run 1 (same setup, earlier) showed the same line, label, revision 4 and
  trace (`rejected`, same codes, 23,091 ms, 1876 / 184 tokens). Its script
  stopped at the reload wait. The throwaway volume was reset with `down -v`
  (the scripted Case id is fixed) and run 2 above recorded the reload state.
- Screenshots (scratch, not committed), in `scratchpad/impl-pr9b2/browser/`:
  `01-after-create.png`, `02-after-first-consumer-turn.png`,
  `03-after-reload.png`, `run1-01-after-create.png`,
  `run1-02-after-first-consumer-turn.png`. Text in `result.json`, the
  post-reload Case read in `run2-case-after-reload.json`, the traces in
  `run2-traces.txt` and `run1-fast-trace.txt`.
- Teardown: only this check's gateway (8776), Runtime (8021), Web (3021)
  and their launchers were stopped; `docker compose -p
  proxyloop-pr9b-browser down -v` removed its container, volume and network.
  `proxyloop-postgres-1`, `proxyloop-postgres-test-1`,
  `proxyloop-temporal-1`, `proxyloop_postgres-data` and
  `proxyloop-portfolio-demo_postgres-data` are unchanged. DB lane released.

### Second-half review remediation

Review (independent `reviewer`, second half: wire switch, M2, split reports,
docs): Request Changes, no Blocking. Artifact:
`harness/code_review/feat-pr9b-local-fast-gateway.md` (second-half section).
All items are root decisions, applied:

- I1: the per-family explanation was wrong in the README, this log and
  `docs/architecture.md` (and the status row). It was re-verified from
  `product-path-report.json` and the M1 report (distilled, true oracle):
  refusal-transfer 40 → 0, unsupported-action 40 → 0, required-feature-loss
  36 → 37, and the other three families unchanged; promotion-credit is
  40/40 true and 0/40 product (the model keeps confirm), unsupported-action
  0/40 true and 40/40 product. All four places were corrected. D4 is about
  half of the drop.
- M1: `docs/architecture.md` "Recorded local limits" now uses the
  product-path timeout figure: 64/200 over 25 s by `generation_ms`, 65/200 by
  `wall_ms`, roughly a third. The trained-path 15/240 is context, and the
  split runs saw 0/16. The same figures are in the README.
- M2: the README Host rule is `127.0.0.1:<port>` or `localhost:<port>`.
  `docs/development.md` says the gateway listens on IPv4 only, so
  `http://[::1]:<port>` fails at startup.
- M3: `check_local_report` binds `gateway_identity` to the committed
  sources. It must equal the M1 report's recorded identity for the backend,
  and the distilled `adapter_fingerprint` must equal the attestation's
  `content_fingerprint`; otherwise the check fails with
  `gateway_identity_not_attested`. Tests on fake-gateway reports pass the
  fake identity explicitly. The check also cross-checks the measured block
  (`<scenario>_measured_inconsistent`):
  - the call count equals applied Fast turns plus unapplied Fast calls, and
    `fast_tokens` has one entry per call;
  - `fast_call_ms` p50 and max are recomputed from the calls;
  - each applied Fast turn has a call at its cursor, whose outcome agrees
    with `fast_result`, `fallback_cause` and `delivered`.

  New tests: committed reports pass for both backends; a self-consistent
  re-identified report, a call turned into a timeout, a dropped call, an
  edited max, and a call moved to another turn each fail. Red: against the
  previous script the five new tamper tests failed (13 failed / 3 passed in
  the file, the other failures from the new argument); green: 29 passed with
  `test_fast_slow_split_report.py`.
- M4: `run_phase03c_product_parity.py --rebuild-from-report` re-derives
  every delivery stage, gate code and aggregate from the committed per-row
  raw outputs (`_observed_from_report`), with no model and no run files.
  `validate_observed` now also requires every generated row's
  `prompt_fingerprint` to equal the recomputed product prompt. The rebuild
  therefore refuses (the model must run again) when a change alters a
  prompt. The `--check` failure message names the rebuild. Documented in
  the README (step 3) and the module docstring. Tests: rebuild with no code
  change gives identical bytes; a derivation change fails `--check`, and
  after a rebuild `--check` passes; a changed prompt fingerprint is refused.
- M5: tests where `main(["--check"])` fails on an edited `raw_output`
  (`stale or was edited`) and on two swapped generated rows (`differ from
  the diverging product rows`). `ml/tests/test_product_parity.py`: 18
  passed.
- Nits:
  - The make variable is `LOCAL_FAST_PORT` (default 8765), and
    `FAST_GATEWAY_URL` defaults to `http://127.0.0.1:$(LOCAL_FAST_PORT)`;
    `make -n` shows `--port 8775` and `--gateway-url
    http://127.0.0.1:8775` for `LOCAL_FAST_PORT=8775`.
  - The M2 `CLAIM_BOUNDARY` adds "Latencies are descriptive (one machine,
    sequential, uncontrolled load), not p95 or capacity". That changed the
    report bytes, so the report was regenerated with `--rebuild-from-report`
    (output `changed`). The diff is `claim_boundary` and
    `report_fingerprint` only (`36b031b9…` → `b37b70f2…`); every count is
    unchanged. `make phase03c-product-parity-check` passes.
  - The stale "Pending (after PR-9a lands)" list was replaced by a status
    note.

Known limit (on the follow-up list): the Web does not restore a Case on a
local Fast backend after a page reload. Restore requires
`adapter_mode=scripted` (with temporal and postgres), so a reload shows
"Runtime state not verified" even though the Runtime still returns the Case
and its line (Browser check above).

### Remaining

1. Follow-up (not PR-9b): the Web's restore rule for a Case on a local Fast
   backend (known limit above).
2. PR, CI, merge.
