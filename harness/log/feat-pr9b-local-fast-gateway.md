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

## Pending (after PR-9a lands)

- M2 input parity through the product rendering path (needs
  `agent_core/fast_observation.py`, 9a).
- Gate pass rate under PR-8's `fast_disclosure_violations` (needs PR-8a).
- Local Fast/Slow split reports (`--fast-backend distilled|untuned`) and
  `fast-slow-split-check` (need `ObservingFastAdapter` and the runtime path).
- After the root says 9a merged: switch the gateway from the interim
  `local_fast/wire.py` to `agent_core/local_fast_wire.py` (its
  `encode_decide_response(DecideResponse)` takes a different argument) and
  delete the interim copy; check the 9a golden fixtures under
  `tests/fixtures/local-fast-wire/` from the ml side (identity goldens =
  the `with_generator` identities; the A20 schema comparison drops
  `description`, the only difference from ml's frozen `FastModelOutput`).
  9a's files are not edited on this branch.
- Docs listed in spec §6.3 item 9 that describe the runtime side
  (`docs/architecture.md`, `docs/development.md`, `docs/ml-evidence.md`).
- The optional Browser check (spec §6.7 step 4).

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
