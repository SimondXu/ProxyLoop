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
- Wire golden fixtures under `tests/fixtures/local-fast-wire/` (9a-owned),
  and the switch of the gateway from the interim `local_fast/wire.py` to
  `agent_core/local_fast_wire.py`, so the wire has one owner.
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
