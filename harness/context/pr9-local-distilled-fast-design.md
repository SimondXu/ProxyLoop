# PR-9 Stage 1b: local distilled Fast backend — frozen spec

Status: frozen by the root orchestrator on 2026-09-24 from the `architect`
proposal below (decisions 16 and 18). Root answers to §8:

- **Q1 (product).** Accepted as proposed: with the PR-8 gate v1, the distilled
  backend is expected to deliver the fallback on most turns (it was trained on
  minor-unit arithmetic and confirm/counter acts). That is reported as the
  headline product number and recorded as a negative result, not hidden. The
  "act-to-template" alternative is **not** adopted: it would change what
  "distilled Fast dialogue" means and make the demo look stronger than the
  model is. It is recorded as a possible later decision only.
- **Q2.** Pre-registered M1 bar adopted (local act agreement ≥ 0.95 and cloud
  concordance ≥ 0.95). Failing it relabels the backend "stack parity not
  established"; it does not remove the backend.
- **Q3.** `agent_core` seam frozen as proposed (`ObservingFastAdapter`, the
  coordinator deriving `SafeObservation`, `capture_fast_failures`, `fast_failed`).
- **Q4.** Confirmed: only a typed, allow-listed `FastAdapterFailure` is captured;
  `FAILED` trace + fallback line + applied command; no retry, no backend switch.
  `OpenAICompatibleAdapter` and Slow failures unchanged.
- **Q5.** `adapter_mode` values `local_distilled_candidate` /
  `local_untuned_baseline` (decision 18's label); payload keys unchanged.
- **Q6.** Placement accepted: ml code under `proxyloop_evaluation/local_fast/`,
  `ml/serving/` for the README and the attestation (frozen `ml/pyproject.toml`).
- **Q7.** Commit per-row raw local outputs in the parity report (03C precedent).
- **Q8.** Done: PR-8 §5.2 amended before 8a lands (`fast_result=failed`,
  `fallback_cause ∈ {null, gate, failure}`).
- **Q9.** `CONTEXT.md` gains "Fast Backend" and "Local Opt-in Candidate" in 9a.
- **Q10.** Timeout 20 s default, 25 s cap; a Fast call blocks other direct
  commands under the B2-8 app lock for its duration — recorded local limit.
- **Q11.** No credential, no hosted spend, no download: the base model must
  already be cached and `HF_HUB_OFFLINE=1` is enforced; a machine without the
  cache stops and asks the user. Publishing the adapter or converted weights is
  a release and is excluded. Weights/adapters are never committed.
- **Q12.** D3–D6 recorded as E1 caveats, not invented product signals.

Split: 9a (runtime seam, R-19, HTTP adapter, fake gateway; CI only; touches
`runtime.py`/`agent_core`) starts after PR-8a merges. 9b (gateway, adapter
conversion, silent-load guard, parity M1/M2, local split reports, manual run)
touches no hot file; its ml-side parts may start before 9a, and it merges after 9a.

---

# PR-9 design proposal — Stage 1b: local distilled Fast backend, gateway, `PROXYLOOP_FAST_BACKEND`, local parity re-measure

Architect proposal, propose mode. Baseline `main` @ `f4a2487` (read from a `git archive` export under
`scratchpad/arch-pr9/src/`; the local `main` checkout is at `c73f6a7`, and `git diff c73f6a7 f4a2487` is empty for
`agent_core`, `contracts`, `ml/evaluation` and `case_runtime/runtime.py`, so the probes ran on the checkout's venvs).
No repository file was edited.

Tags: **[O]** observed in code, data, or a probe (file:line or probe name); **[I]** inferred; **[P]** proposed.

Binding inputs: build plan rows PR-8, PR-9, PR-11 and DoD items 2–3; decisions 16–20 (esp. 17, 18); the frozen PR-8 spec
(`scratchpad/specs/pr8-fast-dialogue-design.md`, including root answer 9); the frozen PR-7 spec
(`scratchpad/specs/r12-model-trace-log-design.md`, root decision 4 = the "adapter raises → no trace" gap).
State of the dependencies [O]: PR-7 is on `fix/r12-model-trace-log` (not merged); PR-8b is on
`feat/pr8b-web-assistant-lines`; **PR-8a has no branch or worktree yet**. This design is written against the frozen
PR-7/PR-8 specs, not merged code.

Probes (read-only; scripts in `scratchpad/arch-pr9/probe/`, run with the checkout's `runtime/.venv` and `ml/.venv`
python, `PYTHONDONTWRITEBYTECODE=1`; `git status` clean afterwards):

```
P1 product view → frozen 03C v6 renderer
   latest_provider_event: provider_offer 'A fictional Provider offer is available.'
   render_prompt(product view) -> ValueError Phase 03B prompt requires the public observation marker
P2 product snapshot → SafeObservationAdapter.build → marker event → render_prompt(v6)
   rendered OK; offers=[{monthly 7200, fees 0, features [mobile_hotspot, unlimited_talk_text], applied_changes []}]
   flags (defaulted): requested_disclosures [], needs_clarification F, transfer_available F,
                      approval_current T, confirmation_evidence_available T
   strategy: "Reduce the recurring bill without losing mobile hotspot access." | "Handle the latest fictional Provider turn safely."
P3 R-19: ProviderOffer with one CREDIT line of -500 → SafeObservationAdapter.build
   -> ValueError fees_minor must be a non-negative integer
P4 approximate gate-v1 pass rate on the committed 03C raw outputs (act ∈ {clarify, challenge, escalate}
   AND no digit AND len(response_text) ≤ 600; an approximation, PR-8a's gate does not exist yet)
   held-out A1 untuned : acts {counter 182, escalate 40, confirm 14, challenge 4}; digits 191/240; pass ≈ 44/240
   held-out A3 distilled: acts {confirm 124, counter 76, escalate 40};             digits 237/240; >600 chars 68; pass ≈ 0/240
   dev      A1 untuned : pass ≈ 71/400      dev A3 distilled: pass ≈ 80/400
```

---

## 1. Current state

### 1.1 The Fast adapter seam [O]

- `FastAdapter.decide(view: FastModelView) -> FastAdapterResult` (`agent_core/interfaces.py:38-41`). Optional
  protocols: `IdentifiedAdapter.model_identity` (`:81-86`), `UsageReportingFastAdapter.decide_with_usage` (`:89-95`).
  The coordinator dispatches on these with `isinstance` (`coordinator.py:540-545`, `:616-633`).
- `CaseCoordinator.advance` (`coordinator.py:159-300`) projects `project_fast_view(snapshot)` (`:331-370`), calls the
  adapter inside `_timed` (`:302-328`), validates with `validate_fast_result` (`:427-472`), and emits one 1.1
  `ModelTrace` per call on 1.1 snapshots with `result = SUCCEEDED | REJECTED` (`:548-613`).
  **An adapter that raises propagates out of `advance` with no outcome and no trace** (there is no `try` around
  `_timed`); `ModelResult.FAILED` exists in the contract (`contracts.py:113-116`) and is never emitted. This is PR-7's
  recorded gap (root decision 4).
- Adapters: `ScriptedFastAdapter` (constant `BOUNDED_FAST_STATUS_TEXT`, `scripted.py:41-73`); PR-8 adds
  `ScriptedDialogueFastAdapter` (spec §3). `OpenAICompatibleAdapter` (`openai_adapter/adapter.py:41-168`) sends the
  **whole `FastModelView` JSON** under its own system prompt (`:177-205`), parses with Structured Outputs into the strict
  runtime-owned `FastModelOutput` and compiles with trusted view metadata (`outputs.py:44-50, 94-129`). Its failures raise
  `OpenAICompatibleAdapterError(kind)` (`errors.py`).

### 1.2 Where Fast is constructed [O]

- `ThinAgentRuntime(fast=None)` → `ScriptedFastAdapter()` (`runtime.py:217`; PR-8 changes the default to
  `ScriptedDialogueFastAdapter`).
- API: `runtime_from_environment` (`api/config.py:29-72`): `PROXYLOOP_RUNTIME_MODE=scripted` → default adapters;
  `=model` → one `OpenAICompatibleAdapter` in **both** slots (needs an API key). `services_from_environment` refuses
  anything but scripted under Temporal (`config.py:88-90`). The workflow worker builds its runtime in
  `activities.py:256-269` (PR-11's file).
- `adapter_mode` is `Literal["scripted", "model"]` (`runtime.py:98`), inferred by `isinstance` on the two adapters
  (`runtime.py:2216-2218`), and exposed verbatim in `/health/live`, `/health/ready` (`api/readiness.py:26, 71`), the
  operation record (`app.py:758`, `operations.py:56, 82`) and the Web readiness parse (`runtime-client.ts:747-756`).
  Tests pin the payloads by exact equality (`test_direct_mode_command_path.py:288-302`,
  `test_phase_04d_control_plane_operations.py:381-393`).

### 1.3 What `project_fast_view` produces [O]

`FastModelView` (`contracts.py:1325-1365`): case id, pins, planning basis (fingerprints only), goal, constraints,
verified facts, strategy, the last 8 visible events, `latest_provider_event`, `pending_slow_work`, all six dialogue acts,
and `allowed_disclosures = strategy ∩ authority`. It carries **no offers, no bill snapshot, no Provider-state flags**.
In the product the latest Provider event is prose: `"A fictional Provider offer is available."` (`runtime.py:751-752`,
probe P1) or a channel message body (`runtime.py:414-415`); offers live only in `snapshot.offers`.

### 1.4 How Phase 03C rendered the Fast prompt [O]

- Training, dev, held-out and the local rescore all use one builder: `phase03c_prompt_set.render_prompt(view,
  prompt_version="v6")` → `Phase03CQwenAdapter.build_prompt` (`phase03c_experiment.py:349-391`) → the 03B compact view
  (`phase03b_experiment.py:542-605`) + `OUTPUT_JSON_SCHEMA` + reason-code line + `DECISION_CONVENTION_BLOCK_V6`
  (`phase03c_experiment.py:169-203`), chat-templated with `enable_thinking=False`, greedy, seed 0, `max_tokens` 512
  (`:584-650`; held-out report `decoding` block).
- The compact view renders only: goal (target minor units, features, forbidden changes), constraint statements, the
  strategy's text fields, allowed acts, `view.allowed_disclosures`, and `latest_public_observation`, which is **parsed
  out of the latest Provider event's content**: that content must be `PHASE_03B_PUBLIC_SAFE_OBSERVATION_V1\n` + a
  `SafeObservation` JSON (`phase03b_experiment.py:652-700`; built by `phase03c_prompt_set.build_parameterised_snapshot`,
  `:124-131, 212-250`). The observation carries offers (`monthly_price_minor`, `total_cost_12_months_minor`,
  `fees_minor`, `features`, `applied_changes`, …) and five Provider-state signals (`requested_disclosures`,
  `needs_clarification`, `transfer_available`, `approval_current`, `confirmation_evidence_available`), produced by
  `SafeObservationAdapter.build` from simulator turns (`phase03c_scenarios.py:151-175`).
- The 03C recipe: Qwen3-8B base `b968826d`, LoRA r32/α64 on q,k,v,o,gate,up,down (`train/adapter/adapter_config.json`
  [O]); evaluation ran on vLLM with a **merged** bf16 checkpoint on an A100 (held-out report `arms.A3.model =
  /scratch/cloud-run-01/train/merged`) [O].

### 1.5 Is the distilled model's prompt format the product's Fast view? **No.** [O unless marked]

| # | Divergence | Evidence | Consequence |
|---|---|---|---|
| D1 | The trained prompt needs the marker + `SafeObservation` in the latest Provider event; the product event is prose. | Probe P1: `render_prompt(product view)` raises. | Serving the adapter requires an **input-parity renderer**; without one the model cannot even be prompted. |
| D2 | The product `FastModelView` has no offers, no bill total, no provider id. | `contracts.py:1325-1341` | The renderer needs the **snapshot**, not the view. `FastAdapter.decide(view)` cannot supply it: a seam change is required (§2.4). |
| D3 | The product has no source for the five Provider-state signals. | `CaseContextSnapshot` has none; probe P2 used `SafeObservationAdapter.build` defaults. | The product renderer must declare constants (no clarification, no requested disclosure, no transfer, approval current, evidence available). Families that depend on them (03C `refusal-transfer`, `disclosure-restriction`, `stale-approval`-type rules 1–5) cannot be reproduced from product input. **E1 made concrete.** |
| D4 | `applied_changes` is always `()` from a `ProviderOffer` (1.1 lacks it, R-11b). | `observation.py:285` | Held-out families driven by applied changes lose their signal on the product path. |
| D5 | The conversation is not in the trained prompt at all: the compact view renders no `recent_events`. | `phase03b_experiment.py:563-570` | On a consumer turn, the distilled Fast answers from the offer and the Case only; it never sees what the consumer said. |
| D6 | Strategy text comes from the product's Slow: `current_subgoal` "Handle the latest fictional Provider turn safely." vs training "Evaluate the current fictional Provider offer."; `primary_objective` = the goal's `desired_outcome` vs "Reduce the recurring bill safely." | `scripted.py:103`, `fresh_fixtures.py:558-559`, probe P2 | Content divergence, not rendering; measurable only on product runs (M3). |
| D7 | Inference stack: vLLM + merged bf16 on CUDA vs MLX on Apple silicon with an unmerged adapter (E2). | §1.4 | Must be measured (M1). |
| D8 | The v6 convention tells the model to write minor-unit arithmetic into `response_text` ("total 112700 vs cap 81600 (6800*12): exceeds"); the trained acts are mostly `confirm`/`counter`. PR-8's gate v1 rejects any number outside the allowed set and every act outside {clarify, challenge, escalate}. | `phase03c_experiment.py:184-193`; PR-8 spec §2.2; probe P4 | **In the product, the distilled Fast line will be withheld and replaced by the fallback on almost every turn** (≈ 0/240 held-out outputs pass an approximation of gate v1). This is the most important product-level finding of this design; see root question Q1. |

Parity is the core risk, and D1–D5 make it structural: the product can never produce the trained input exactly.
What the design can do is (a) make the rendering path single-owner and byte-identical to 03C where inputs agree, and
(b) **measure** the rest instead of claiming it.

---

## 2. The gateway and the runtime HTTP Fast adapter

### 2.1 Process model: a separate loopback-only MLX process, reusing the measured 03C code path [P]

`uv run --project ml --extra evaluation python -m scripts.run_local_fast_gateway --backend distilled|untuned
--model-path <HF snapshot> [--adapter-path <MLX adapter dir>] --port 8765`, bound to `127.0.0.1` only.

Why a separate process:
- `runtime/` never imports `ml/` (`ml/README.md`: "Runtime packages and services never import this workspace") and
  `mlx-lm` exists only in the ml lock, darwin/arm64 only (`ml/pyproject.toml` `evaluation` extra) [O].
- The ~17 GB model load stays out of API and worker processes (Stage 0 measured `mlx_peak_memory_bytes` 17,130,948,648
  for 8B bf16 on this machine, `results/arm-a-untuned-8b-v4.json`) [O]; one gateway can serve the API now and the
  Temporal worker in PR-11.
- `docs/architecture.md:84` already anticipates "model serving behind a process boundary, but it must preserve the same
  typed protocols" [O]; this design keeps `FastAdapter` and adds one optional protocol.

Inside, the gateway wraps `Phase03CQwenAdapter(model_path, adapter_path, model_spec=QWEN3_8B_BF16_SPEC,
prompt_version="v6", max_tokens=512)` and calls its `generate(view)` — the exact class and decoding profile the 03C
local rescore replays (`scripts/rescore_phase03c_heldout.py`) [O]. It already supports `mlx_lm.load(model,
adapter_path=…)`, greedy sampling with an explicit seed, `enable_thinking=False`, strict/tolerant parse, and base-model
attestation (`phase03c_experiment.py:298-327, 612-695`; `qwen_spec.py` `QWEN3_8B_BF16_SPEC` pins MLX export
`6766fd4b…`) [O]. The snapshot is already in the local HF cache (`~/.cache/huggingface/hub/models--Qwen--Qwen3-8B-MLX-bf16`)
[O]. No existing ml file is edited.

Rejected alternatives:

| Alternative | Why rejected |
|---|---|
| llama.cpp (`llama-server` + GGUF) | Needs a GGUF conversion of base and LoRA (torch/transformers tooling not in the frozen ml lock) and a new binary outside both locks; a third inference stack moves further from the measured one (worse E2); no attestation path exists. |
| `mlx_lm.server` (OpenAI-compatible) + reuse `OpenAICompatibleAdapter` | The runtime would have to own the trained v6 prompt (a second copy of frozen ml bytes, parity only by test) and the observation. `OpenAICompatibleAdapter` sends the full view under a different prompt and needs Structured Outputs; it also sits in both slots and needs an API key. `mlx_lm.server` offers no attestation, no LoRA self-check, and more HTTP surface. |
| In-process MLX inside the API/worker | Breaks the runtime→ml import rule; puts 17 GB and Metal into every runtime process; Linux CI could not import it. |
| Gateway receives the whole `CaseContextSnapshot` and renders everything | Least privilege: the snapshot carries approvals, Evidence, the manifest and all events; the Fast model must see only the allow-listed view + `SafeObservation`. |
| Fused (merged) MLX weights via `mlx_lm.fuse` | Closer to the cloud's merged model, but a second ~16 GB artifact on disk; keep as the fallback if M1 shows the unmerged adapter diverges (§7 R3). |

### 2.2 Packaging constraint: nothing existing in `ml/` may change [O]

- `hosted_rerun._R4_EXECUTION_PATHS` (`hosted_rerun.py:62-75`) binds `ml/pyproject.toml`, **`ml/uv.lock`**,
  `fast_output.py`, `qwen_mlx.py`, `runner_v2.py` and others; `test_contract_state_is_unchanged_on_the_committed_tree`
  (`ml/tests/test_hosted_rescore.py:410-420`) fails on any byte change. The 03C smoke artifacts additionally bind the
  sources of `phase03c_experiment.py`, `qwen_spec.py`, `fast_parse.py` and `run_phase03c_smoke.py`
  (`scripts/run_phase03c_smoke.py:110-121`). Memory fact verified.
- Consequences: no new ml dependency (so the gateway uses stdlib `http.server`); no new top-level ml package (the wheel
  `packages` list is in the frozen `pyproject.toml`), so **implementation modules go under a new subpackage
  `proxyloop_evaluation/local_fast/`** (precedent: `proxyloop_evaluation/phase03c_training/`), with `ml/serving/`
  holding the README and the committed adapter-conversion attestation. This deviates from the build plan's
  "`ml/serving/`" key-file sketch for a technical reason (root question Q6).
- `agent_core`'s `pyproject.toml` dependencies must not change either: `ml/uv.lock` records them for the path
  dependency, so a new declared dependency would move a frozen file [I]. New `agent_core` modules are fine (the lock
  does not hash sources) [I; `make lock-check` proves it].

### 2.3 Adapter conversion and attestation [P]

- The PEFT adapter exists locally and is git-ignored [O]: `data/experiments/phase-03c/training/cloud-run-01/train/
  adapter/adapter_model.safetensors` (333 MB; `.gitignore:31,53`); `adapter_config.json` is committed; the expected
  source hash `61c29e19…` is in `train/run-manifest.json` `adapter_sha256` [O].
- `mlx-lm` 0.31.3 loads MLX-format adapters only: `adapter_config.json` with `fine_tune_type`, `num_layers`,
  `lora_parameters {rank, scale, dropout, keys}` and `adapters.safetensors` with `…lora_a` shaped (in, r) and `lora_b`
  (r, out); forward is `y + scale·(x·a)·b` (`mlx_lm/tuner/utils.py:113-138`, `tuner/lora.py:67-100`) [O].
  `_attest_phase03b_adapter` requires exactly that pair (`phase03b_experiment.py:373-402`) [O].
- Converter (pure `mlx.core` load/transpose/save, no new dependency): PEFT `…layers.N.<module>.lora_A.weight` (r, in) →
  `model.layers.N.<self_attn|mlp>.<module>.lora_a` = Aᵀ; `lora_B.weight` (out, r) → `lora_b` = Bᵀ; `scale = α/r = 2.0`;
  `dropout 0`; `num_layers 36`; dtype kept (no rounding). Output goes to
  `…/cloud-run-01/train/mlx/adapters/`, already ignored by `data/experiments/phase-03c/training/**/adapters/`
  (`.gitignore:52`) [O]. The exact key names are to be verified by the implementer against the installed `mlx_lm` [I].
- **Silent-failure hazard [O]:** `load_adapters` calls `model.load_weights(…, strict=False)` and `lora_b` initialises to
  zeros. A mis-named key loads nothing and the "distilled" model **is the untuned model**, silently. Required guard:
  after load, the gateway counts LoRA layers and refuses to start unless there are exactly 36 × 7 = 252 and every
  `lora_b` is non-zero.
- Attestation (committed, hashes only): `ml/serving/phase-03c-cloud-run-01-mlx-attestation.json` = source PEFT sha256,
  converter version, and a content fingerprint over sorted `(key, dtype, shape, sha256(tensor bytes))` (robust to
  safetensors container ordering). The `distilled` gateway refuses to start if the base snapshot fails
  `attest_qwen_spec(…, QWEN3_8B_BF16_SPEC)` or the adapter fingerprint differs from the committed one.

### 2.4 The seam change: the coordinator supplies a `SafeObservation` [P]

D2 forces a choice: the adapter must get Case data the view does not carry. Proposed, additive and opt-in:

```python
# agent_core/interfaces.py (additive)
@runtime_checkable
class ObservingFastAdapter(Protocol):
    """Optional: a Fast adapter whose model input needs the public observation."""
    def decide_observed(
        self, view: FastModelView, observation: SafeObservation
    ) -> tuple[FastAdapterResult, ModelCallUsage]: ...
```

- The coordinator, and only it, derives `fast_public_observation(snapshot)` from the **same snapshot** it projects the
  view from, and calls `decide_observed` when the adapter implements the protocol. The adapter never sees the snapshot.
- ML adapters do not implement it, so the ML path is byte-identical (PR-8 I5 preserved).
- Rejected: extend `FastModelView` with offers (canonical contract change, moves committed bytes, decision 19's
  byte-identity rule); a runtime-side per-call "bind snapshot" wrapper (splits snapshot→model-input projection across
  two modules; the coordinator already owns it); an adapter that reads the repository (TOCTOU with pins).

### 2.5 Endpoint contract (`local-fast-wire-v1`) [P]

One owner for the wire: a new stdlib-only module `agent_core/local_fast_wire.py` (both envs import `agent_core`; no
pydantic import in `agent_core`, no dependency change). Golden fixtures under `tests/fixtures/local-fast-wire/` pin the
bytes from both sides.

| Endpoint | Request | Response |
|---|---|---|
| `GET /v1/identity` | — | `200 {wire_version, backend: "distilled"\|"untuned", label: "local opt-in candidate"\|"untuned local baseline", base_model, base_revision, adapter_fingerprint \| null, prompt_version "v6", compiler_version, observation_renderer_version, trained_view_version, decoding_fingerprint, mlx_versions, identity_fingerprint}` |
| `POST /v1/fast/decide` | `{wire_version, view: FastModelView JSON, observation: SafeObservation.to_dict()}`, ≤ 256 KiB | `200 {wire_version, identity_fingerprint, status: "succeeded"\|"invalid_output"\|"unrenderable", output: {dialogue_act, fact_updates, reasoner_request, completion_claim, response_text, action_intent} \| null, detail_code \| null, usage: {input_tokens, output_tokens, generation_ms}}`; `400 request_invalid`; `413`; `503 busy`; `500 gateway_error`. All error bodies content-free. |

Gateway behaviour:
1. Parse; check `observation.case_id/case_revision/constraint_set_revision` against `view` (else 400).
2. `trained_view(view, observation)`: replace `latest_provider_event.content` (and its `recent_events` entry) with
   marker + canonical observation JSON. Probe P2 shows this renders under the frozen v6 builder [O].
3. `Phase03CQwenAdapter.generate(trained_view)` (also runs the D3-2 private-value guards). Status `SUCCEEDED` → return
   the six semantic fields; `INVALID_OUTPUT` → `invalid_output` + an allow-listed `detail_code` (`invalid_json`,
   `schema_validation_error`, `thinking_leak`, `output_too_large`, …); guard/render errors → `unrenderable`.
4. **Single-flight**: `ThreadingHTTPServer` so `/v1/identity` answers during generation; `decide` takes a
   non-blocking lock and returns `503 busy` if held. No queue.
5. Never returns ids, pins or raw text; logs only status, latency and token counts (no prompt, no output).

### 2.6 How the runtime adapter maps a call to a Fast decision [P]

New runtime workspace package `runtime/packages/local_fast` (`proxyloop_local_fast`, deps: `agent_core`,
`contracts`, `openai_adapter` for its strict `FastModelOutput` + `compile_fast_output`; stdlib `http.client`).

```python
class LocalFastHttpAdapter:            # FastAdapter + ObservingFastAdapter + IdentifiedAdapter
    @classmethod
    def connect(cls, *, base_url: str, backend: Literal["distilled", "untuned"],
                timeout_s: float = 20.0) -> LocalFastHttpAdapter: ...   # probes /v1/identity, fail closed
    model_identity: ModelIdentity
    fast_backend_label: Literal["local_distilled_candidate", "local_untuned_baseline"]
    def decide(self, view: FastModelView) -> FastAdapterResult: ...      # raises FastAdapterFailure("fast_input_unrenderable")
    def decide_observed(self, view: FastModelView, observation: SafeObservation
                        ) -> tuple[FastAdapterResult, ModelCallUsage]: ...
```

- `succeeded` → `FastModelOutput.model_validate_json(json.dumps(output))` (JSON mode: strict mode rejects enum strings
  in python mode) → **reject non-empty `fact_updates` as `invalid_output`** (the v6 convention requires `[]`; a model
  fact update with invisible provenance would otherwise fail the consumer's command with 409 via
  `fact_provenance_not_visible`) → `compile_fast_output(view, output)` with the runtime's trusted view, so ids and pins
  are never taken from the gateway → `ModelCallUsage(input_tokens, output_tokens, latency_ms = client end-to-end)`.
- Every other outcome raises `FastAdapterFailure(code, detail_code=…)` with `code` from a closed allow-list:
  `fast_adapter_timeout` (socket timeout / deadline), `fast_adapter_unavailable` (refused/reset), `fast_adapter_busy`
  (503), `fast_adapter_protocol_error` (bad status, oversize >64 KiB, bad JSON, duplicate keys, wrong wire version),
  `fast_adapter_invalid_output` (gateway `invalid_output`, local schema failure, non-empty `fact_updates`),
  `fast_adapter_identity_mismatch` (response `identity_fingerprint` ≠ the one probed at `connect`),
  `fast_input_unrenderable` (gateway `unrenderable`, or the coordinator's renderer refused; §5).
- Loopback only: `connect` refuses any host other than `127.0.0.1`, `::1`, `localhost`; no redirects; no credential.

### 2.7 Timeouts [P]

- `PROXYLOOP_FAST_TIMEOUT_S`, default **20**, validated to (0, 25]. Budget: PR-11's 30 s activity limit (build plan) and
  the 30 s Next proxy timeout (status file, R-1 alternative (d)) [O]; scripted Slow costs ~0 ms, leaving ≥ 5 s for the
  rest of the command.
- `http.client` timeouts are per socket operation; the gateway writes the body once after generation, so the socket
  timeout bounds time-to-first-byte, and the adapter also checks a monotonic deadline after the read [I].
- Expected latency [I, from observed numbers]: Stage 0 ran untuned 8B bf16 on this machine; distilled outputs are longer
  (held-out A3 `output_p50` 194, `p95` 223 tokens vs A1 81/111 [O]). At an estimated 15–20 tok/s decode plus ~2k-token
  prefill, a distilled call is ~10–16 s; a 512-token worst case exceeds 20 s and becomes a `fast_adapter_timeout`
  fallback. MLX cannot cancel a running generation, so the next call inside that window gets `503 busy` → fallback.
  Stated as a limit; no p95 or capacity claim (decision 18).

### 2.8 Deterministic per-call fallback (answers PR-8 root question 9) [P]

- `CaseCoordinator(..., fast_gate=None, capture_fast_failures: bool = False)`; `CoordinatorOutcome.fast_failed: bool =
  False`. With capture on (only the runtime's `_coordinator()` sets it, next to PR-8's `fast_gate`), a
  `FastAdapterFailure` raised by the Fast call is caught; the coordinator emits a Fast `ModelTrace` with
  `result=FAILED`, `reason_codes=(code[, detail_code])`, `output_ref=None`, `output_schema_version="none"`, tokens from
  the failure's usage (else 0), latency from the call window; `fast_decision=None`, `fast_failed=True`. PR-7's `_advance`
  appends it before the runtime acts (PR-7 I6), which **closes PR-7's recorded gap for Fast**.
- The runtime (PR-8's `_append_event_serialized` branch) treats `fast_failed` like `fast_disclosure_rejected`: deliver
  `FAST_FALLBACK_TEXT` as the `assistant_message`, apply the command, emit no `fast` echo.
- Only `FastAdapterFailure` is captured. Any other exception (a bug, `OpenAICompatibleAdapterError`, a Slow failure)
  propagates exactly as today — no masking. Validation rejects keep PR-8 I3 (409, no state change).
- **Distinct from the excluded "automatic fallback under load"** (decision 18): the rule is a pure function of one
  call's outcome; there is no retry, no load or latency detection, no circuit breaker, no switch to another backend or
  model, no capacity claim. The backend label stays `distilled` and every fallback is a visible `FAILED` trace. The
  channel path is unchanged (still fails closed on a non-constant Fast, PR-8 I7) and is unreachable here because
  Temporal refuses non-scripted Fast until PR-11.

### 2.9 `PROXYLOOP_FAST_BACKEND` selection and labelling [P]

| Variable | Values | Rule |
|---|---|---|
| `PROXYLOOP_FAST_BACKEND` | `scripted` (default) \| `distilled` \| `untuned` | Only with `PROXYLOOP_RUNTIME_MODE=scripted` (Slow stays scripted, decision 17); with `model` → `ValueError`. Under `PROXYLOOP_ORCHESTRATION_MODE=temporal` any non-scripted value → `ValueError` until PR-11. |
| `PROXYLOOP_FAST_GATEWAY_URL` | default `http://127.0.0.1:8765` | loopback only |
| `PROXYLOOP_FAST_TIMEOUT_S` | default `20` | (0, 25] |

- One selector, `proxyloop_local_fast.fast_adapter_from_environment(values) -> LocalFastHttpAdapter | None`, called by
  `api/config.py` now and by the worker in PR-11 (leverage: one parse, one validation). `connect` fails the process
  start if the gateway is absent or reports a different backend: an opt-in that silently delivered fallbacks would
  mislabel the run.
- Rollback ("untuned/scripted rollback", decision 18) = set the variable back and restart. Never automatic.
- Labels:
  - `adapter_mode`: extend `AdapterMode` with `"local_distilled_candidate"` and `"local_untuned_baseline"`, inferred
    from an `agent_core` `LabelledFastBackend` protocol (`fast_backend_label`) when Slow is scripted. Payload keys do not
    change, so the exact-equality tests stay green; only opt-in runs show new values (root question Q5).
  - `ModelTrace` identity per call: `provider="local_mlx_gateway"`, `model="Qwen/Qwen3-8B-MLX-bf16"`,
    `model_version="<backend>:<identity_fingerprint[:16]>"`, `adapter_version="local-fast-http-v1"`,
    `prompt_version="phase-03c-v6+fast-observation-v1"`.
  - Reports and docs: "local opt-in candidate" (distilled) / "untuned local baseline"; never "promoted" or
    "production"; the four 03C caveats + E1–E5 travel with every number.

---

## 3. The parity re-measure (decision 18: pre-registered, local)

### 3.1 Pre-registration (frozen in the PR-9 spec before any local model run) [P]

| Id | What | Inputs | Model calls | Bar |
|---|---|---|---|---|
| **M1 stack parity (E2)** | Local MLX distilled and untuned on the **trained-format** prompts of the same 240 held-out rows (rebuilt deterministically from the reserved seeds exactly as `rescore_phase03c_heldout.build_index` does). Metrics: act agreement vs oracle (cloud 0.983 / 0.542); per-row act concordance with the committed cloud A3/A1 outputs; schema validity; policy violations; per-row templated `input_tokens` equality with the cloud report (a cheap chat-template parity check); raw-output exact-match rate. | 240 rows × {untuned, distilled} | 480 | **Proposed**: "stack parity held" iff distilled local act agreement ≥ 0.95 **and** local-vs-cloud act concordance ≥ 0.95; otherwise "stack parity not established". Untuned: reported, no bar. |
| **M2 input parity (E1)** | The same 240 rows rendered through the **product rendering path**: the held-out snapshot with the latest Provider event as plain `provider_turn.message`, observation from `fast_public_observation(snapshot)`, then `trained_view` + v6. Deterministic part: product-path vs trained-path prompt fingerprints per row, and a divergence class per row (flags defaulted / applied_changes dropped / requested_disclosures dropped / none). Model part: act agreement vs (a) the oracle on the true observation and (b) the oracle on the product-rendered observation. | rows whose product-path prompt differs × {untuned, distilled} (identical prompts reuse M1 outputs) | ≤ 480 | Descriptive only. (a)−(b) is renderer information loss, independent of the model. |
| **Gate pass rate** | PR-8's `fast_disclosure_violations` on every M1/M2 output compiled against its row snapshot; histogram of `fast_gate_*` codes. | all M1/M2 outputs | 0 | Descriptive. Probe P4 predicts ≈ 0 for distilled. |
| **M3 product runs** | The PR-8 split scenarios S1/S2 through the real runtime and gateway (§4). | 2 scenarios × {untuned, distilled} | a handful | Descriptive; latency p50/max on one machine only. |

M2 isolates the renderer (the observation path). D6 (strategy text from the product's Slow) is product content and is
visible only in M3. A failed M1 bar does not delete the backend; it changes its label (root question Q2).

### 3.2 Recording without committing forbidden artifacts [P]

- **Never committed**: the PEFT and MLX adapter tensors, base weights, the merged model, the cloud bundle JSONL
  (already ignored, `.gitignore:49-60`) [O], resumable per-row run files (new ignore rule
  `data/experiments/phase-03c/local-parity/**/*.jsonl`).
- **Committed** (reviewed): `data/experiments/phase-03c/local-parity/parity-report.json`, containing identity and
  attestation fingerprints, host facts (chip, memory, macOS, `mlx`/`mlx-lm` versions), decoding profile, per-row metadata,
  per-row raw outputs, metrics, the pre-registered bar and verdict, and a `claim_boundary`. Committing raw outputs
  follows the 03C precedent (the committed `heldout-report.json` carries `raw_output` per row [O]) and makes the scores
  replayable (root question Q7). Model text is fictional-scenario output: no PII, no teacher text.
- The PR log records the commands, wall time, and the commit SHA; the conversion attestation JSON is committed under
  `ml/serving/`.
- Every `make` target that loads a model sets `HF_HUB_OFFLINE=1`, so no download can happen implicitly.

### 3.3 What CI checks, with the fake gateway and without a model [P]

- **Runtime (PR-9a)**: an in-test fake gateway (stdlib `http.server` on `127.0.0.1:0` in a thread) implementing
  `local-fast-wire-v1` with scripted behaviours: success, slow (> timeout), refused port, 503, malformed JSON, oversize,
  wrong wire version, `invalid_output`, `unrenderable`, identity flip, non-empty `fact_updates`, gate-violating text.
  Each drives the real `LocalFastHttpAdapter` through `ThinAgentRuntime` (direct API) and asserts the delivered line, the
  trace result and codes, and the applied command.
- **ML (PR-9b)**: the gateway's HTTP layer and core with `Phase03CQwenAdapter(generator=…)` (no MLX import; the class
  loads `mlx_lm` lazily [O]), the converter on a tiny synthetic PEFT file, the LoRA self-check on a fake module tree, and
  the wire golden fixtures (the ml side serialises a real gateway response and must equal the golden that the runtime
  side parses).
- **`make phase03c-local-parity-check`** (in `make test`): rebuilds the 240 rows, recomputes trained-path and
  product-path prompt fingerprints and divergence classes (deterministic), re-scores the committed raw outputs through
  the repository evaluator and PR-8's gate, and checks the report fingerprint. Model outputs are observed; everything
  derived from them is replayed.
- Frozen-bytes guard: `make lock-check`, `hosted-rerun-check`, `phase03c-smoke-check`, `phase03c-rescore-check` and the
  r4 state test pass unchanged; `git diff --stat main -- <frozen list>` is empty.

---

## 4. The Fast/Slow split for scripted, distilled and untuned (DoD item 3) [P]

- Extend PR-8's `scripts/run_fast_slow_split_report.py` with `--fast-backend {scripted,distilled,untuned}` and
  `--gateway-url`. Scripted is unchanged (`--write|--check`, replayed in `make test`). For the two local backends,
  `--write` requires a running gateway whose identity matches, runs S1 and S2 in-process with the in-memory repository
  and PR-8's stepping clock, and writes `data/evaluation/fast-slow-split-distilled.json` / `-untuned.json`.
- Contents: `schema_version`, `fast_backend`, `label`, gateway identity (full fingerprints), `fast_gate_version`,
  `fast_observation_version`, host facts, per-turn records (class, slow/fast calls, `fast_result`, `delivered`,
  `fallback_cause ∈ {gate, failure}`, codes; **no model text**), aggregates, a measured block (per-role latency p50/max,
  `time_to_line_ms` by class, tokens), `claim_boundary` ("local opt-in candidate; one Apple-silicon machine; sequential
  calls; not p95, capacity or production latency; E1–E5 and the four 03C caveats apply"), `report_fingerprint`.
- `make fast-slow-split-check` verifies the two local files for integrity only: fingerprint, schema, labels, no text
  keys, aggregates recomputed from the per-turn records, and **structural invariance**: turns, classes and Slow calls must
  equal the scripted replay. This holds by construction because Fast cannot change routing (no fact updates, L8).
- Committed for DoD 3: the three split files plus the parity report. Coordination note: PR-8a has not started [O];
  amend PR-8 spec §5.2 now so the record carries `fast_result = failed` and `fallback_cause` from day one. Otherwise
  PR-9 bumps the report schema and regenerates the scripted file (deterministic, but churn) (root question Q8).

---

## 5. R-19 within PR-9 [P]

Reproduced by probe P3 [O]. The product renderer must be total over contract-valid snapshots; `SafeObservationAdapter`
is shared with the ML pipeline, whose outputs must not move.

- Add to `agent_core/observation.py` a total classifier `classify_provider_offer(offer, *, provider_id, case_id) ->
  SafeOffer | tuple[str, ...]`. It returns reason codes for every contract-valid input that makes `SafeOffer.__post_init__`
  raise today (`offer_fee_sum_negative`, `offer_features_duplicate`, plus `offer_case_mismatch`,
  `offer_provider_mismatch`, and any negative-amount or term case the differential fuzz finds, mirroring B1-9's
  method).
- `SafeObservationAdapter.build` keeps its signature and, for `ProviderOffer` inputs, delegates to the classifier and
  raises `ValueError` with **today's exact message** per code. Result: identical return values wherever it returned
  before, a `ValueError` wherever it raised before. A differential test proves it (B1-9 precedent: 20k fuzz, 0
  differences).
- New `agent_core/fast_observation.py`: `FAST_OBSERVATION_VERSION = "fast-observation-v1"`,
  `fast_public_observation(snapshot) -> SafeObservation | ObservationRefusal`. It uses the declared Provider-state
  defaults (D3) and refuses with codes on a missing bill snapshot, no Provider event, no offer, mixed providers, or any
  classifier code. The coordinator turns a refusal into `FastAdapterFailure("fast_input_unrenderable", detail=…)`, so the
  model is never called with a distorted observation and the user gets the fallback.
- Close R-19 in `audit-remediation-status.md` §4a with "made total by refusal codes; the ML `build` path is unchanged on
  every previously-returning input".

---

## 6. Recommendation

### 6.1 Frozen interface sketch [P]

```python
# agent_core/interfaces.py  (additive)
FAST_ADAPTER_FAILURE_CODES: Final[frozenset[str]]   # the seven codes of §2.6
class FastAdapterFailure(RuntimeError):
    def __init__(self, reason_code: str, *, detail_code: str | None = None,
                 usage: ModelCallUsage | None = None) -> None: ...   # codes outside the allow-lists -> ValueError
@runtime_checkable
class ObservingFastAdapter(Protocol):
    def decide_observed(self, view: FastModelView, observation: SafeObservation
                        ) -> tuple[FastAdapterResult, ModelCallUsage]: ...
@runtime_checkable
class LabelledFastBackend(Protocol):
    @property
    def fast_backend_label(self) -> str: ...

# agent_core/observation.py  (R-19, additive + delegation)
def classify_provider_offer(offer: ProviderOffer, *, provider_id: str, case_id: str
                            ) -> SafeOffer | tuple[str, ...]: ...

# agent_core/fast_observation.py  (new)
FAST_OBSERVATION_VERSION: Final = "fast-observation-v1"
@dataclass(frozen=True, slots=True)
class ObservationRefusal:
    reason_codes: tuple[str, ...]
def fast_public_observation(snapshot: CaseContextSnapshot) -> SafeObservation | ObservationRefusal: ...

# agent_core/local_fast_wire.py  (new, stdlib only)
LOCAL_FAST_WIRE_VERSION: Final = "local-fast-wire-v1"
def encode_decide_request(view: FastModelView, observation: SafeObservation) -> bytes: ...
def decode_decide_request(body: bytes) -> tuple[FastModelView, SafeObservation]: ...   # gateway side
def encode_decide_response(...) -> bytes: ...
def decode_decide_response(body: bytes) -> DecideResponse: ...                          # raises WireError
def decode_identity(body: bytes) -> GatewayIdentity: ...

# agent_core/coordinator.py  (additive)
CaseCoordinator(..., fast_gate: FastGate | None = None, capture_fast_failures: bool = False)
CoordinatorOutcome.fast_failed: bool = False

# case_runtime/runtime.py  (small)
AdapterMode = Literal["scripted", "model", "local_distilled_candidate", "local_untuned_baseline"]
# _coordinator(): + capture_fast_failures=True ; delivery: fast_failed -> FAST_FALLBACK_TEXT

# runtime/packages/local_fast  (new)  proxyloop_local_fast.LocalFastHttpAdapter, fast_adapter_from_environment

# ml: proxyloop_evaluation/local_fast/  (new)
TRAINED_VIEW_VERSION: Final = "phase-03c-trained-view-v1"
def trained_view(view: FastModelView, observation: SafeObservation) -> FastModelView: ...
class LocalFastGatewayCore:            # load(): attest base, attest adapter, load, LoRA self-check
    def decide(self, view, observation) -> GatewayResult: ...   # includes raw text for the parity harness only
def serve(core: LocalFastGatewayCore, *, host: Literal["127.0.0.1"], port: int) -> None: ...
def convert_peft_lora_to_mlx(src: Path, dst: Path, *, expected_source_sha256: str) -> ConversionAttestation: ...
```

### 6.2 Invariants [P]

- **L1** The runtime never imports `ml/`; the gateway is a separate process bound to loopback; the client refuses
  non-loopback URLs. No credential exists anywhere on this path.
- **L2** One owner per rendering half: product half `fast_public_observation` (agent_core); trained half `trained_view`
  + the frozen `render_prompt(v6)` (ml). The gateway and the parity harness call the same functions. There is no second
  copy of the v6 prompt.
- **L3** Served decoding profile = measured profile (greedy, temperature 0, seed 0, `max_tokens` 512,
  `enable_thinking=False`, v6). The identity fingerprint binds it, and the parity report records the identity it measured.
- **L4** The gateway fails closed at start: base attestation, adapter content fingerprint = committed attestation,
  252 LoRA layers all with non-zero `lora_b` (the `strict=False` guard).
- **L5** The runtime fails closed at start (identity backend = `PROXYLOOP_FAST_BACKEND`); per call, a response identity
  that differs from the one probed at start → `FAILED(identity_mismatch)`.
- **L6** Deterministic per-call fallback: only `FastAdapterFailure` → `FAILED` trace + fallback line + applied command.
  No retry, no backend switch, no load logic. Everything else propagates.
- **L7** The ML path is untouched: the capture flag and the observing dispatch are opt-in; no frozen file is edited;
  `ml/pyproject.toml` and `ml/uv.lock` are unchanged; `agent_core` dependencies are unchanged; every committed
  `*-check` is byte-identical.
- **L8** The local backend proposes no fact updates (non-empty → `invalid_output`), so Fast cannot change routing or state.
- **L9** Content-free: no prompt, raw output or withheld text in logs, traces (`output_ref=None` on FAILED), API bodies,
  or the gateway's HTTP responses. Only the parity report stores raw outputs, and only for held-out fictional rows.
- **L10** Labels: traces name the backend and identity; `adapter_mode` distinguishes it; reports carry "local opt-in
  candidate" / "untuned local baseline" and the claim boundary.
- **L11** Temporal refuses non-scripted Fast until PR-11; the timeout is ≤ 25 s.
- **L12** R-19: the classifier is total; `build` is unchanged on every previously-returning input and raises `ValueError`
  on exactly the previously-raising ones.
- **L13** Across backends, split reports differ only in Fast outcome and measured fields, never in turn structure.

### 6.3 Acceptance criteria

1. With `PROXYLOOP_FAST_BACKEND=distilled|untuned` and a matching gateway, every applied consumer event yields exactly
   one `assistant_message`: the gate-passed model line or `FAST_FALLBACK_TEXT`. The Fast trace carries the local
   identity, and `adapter_mode` is the new label.
2. Timeout, refused, busy, protocol error, invalid output, unrenderable input, identity mismatch, and non-empty fact
   updates each give: 200, the fallback line, the command applied (approval per policy), a `FAILED` Fast trace with the
   allow-listed code, and no `fast` echo. An unexpected exception still propagates.
3. Startup refuses: an unknown backend value, a non-loopback URL, a timeout outside (0, 25], `RUNTIME_MODE=model` + a
   local backend, Temporal + a local backend, a missing gateway, and a backend mismatch.
4. R-19: contract-valid credit or duplicate-feature offers produce a refusal, not an exception, on the product path.
   The differential test shows `build` unchanged elsewhere.
5. The gateway refuses to start on a wrong base snapshot, a wrong adapter fingerprint, or a failed LoRA self-check.
   It binds loopback only, answers `503` when busy, and logs no content.
6. For a row whose product-path observation equals the true observation, the product-path prompt is byte-identical to
   the trained prompt (parity by construction).
7. The parity report and the two local split reports are committed. Their `--check` targets pass in `make test`
   without a model, and the PR log records the manual run.
8. Every committed `*-check` is byte-identical; `make lock-check` passes; the frozen-path diff is empty.
9. Docs:
   - `docs/architecture.md`: the Fast backend section, and the line-98 wording (`ml/serving` = local opt-in MLX
     gateway; promoted vLLM serving still deferred).
   - `docs/development.md`: the variables and the gateway runbook.
   - `docs/ml-evidence.md`: the parity results with all caveats.
   - `harness/context/audit-remediation-status.md`: R-19 closed, stage 1b.
   - `CONTEXT.md`: terms per Q9.
   - One `harness/log/` file per PR.

### 6.4 Red-first test list

**9a — red on `main` after PR-8a (record the failing output):**

- **F1** `test_fast_adapter_failure_delivers_fallback_with_failed_trace`: a fake Fast raising
  `FastAdapterFailure("fast_adapter_timeout")` through the direct API. Today it errors with no trace (PR-7 gap).
- **F2** `test_product_observation_is_total_for_contract_valid_offers`: a credit offer on the product path. Today it
  raises (P3).
- **F3** `test_local_fast_backend_requires_scripted_runtime_and_direct_mode`: the config refusals.

**9a — green and invariant tests:**

- **A1…A11** Fake-gateway transport matrix (§3.3), each through `ThinAgentRuntime`.
- **A12** Identity probe at `connect` and per-response identity check.
- **A13** Loopback refusal.
- **A14** `adapter_mode` label values, and the unchanged payload keys on scripted runs (existing exact-equality tests stay
  green).
- **A15** ML regression guard: a coordinator with neither a gate nor capture, plus an adapter that raises
  `FastAdapterFailure`, propagates it exactly as on `main`.
- **A16** The observing dispatch is used only for `ObservingFastAdapter`. The observation is derived from the same
  snapshot as the view (same case, revision, pins).
- **A17** A renderer refusal becomes `FAILED(fast_input_unrenderable)` without calling the adapter.
- **A18** R-19 differential fuzz: previously-returning inputs are identical; previously-raising inputs raise
  `ValueError` with the same message.
- **A19** The wire golden fixtures decode on the runtime side.
- **A20** The runtime `FastModelOutput` JSON schema equals the committed golden, which the ml side also pins against
  its frozen copy.
- **A21** PR-7's G8 guard (one `.advance(`) still holds.
- **A22** Channel ingest with the scripted default is unchanged.

**9b (ml):**

- **G1** The gateway core with an injected generator: the product-path prompt is byte-equal to
  `render_prompt(render_prompt_view(scenario, position))` when the observations agree. Its HTTP response matches the
  golden fixture.
- **G2** The converter on a synthetic 2-layer PEFT file: names, transposes, scale, attestation stability, and refusal of
  unknown or missing keys and a wrong source hash.
- **G3** The LoRA self-check rejects zero `lora_b` or a wrong layer count.
- **G4** The HTTP layer: loopback bind, body cap, 503 while busy, 400 on a view/observation mismatch, and no content in
  captured logs.
- **G5** The converted-adapter default path is git-ignored (`git check-ignore`).
- **P1** `phase03c-local-parity-check`: the deterministic parts recompute, and a tampered raw output fails.
- **P2** The split-report check: structural invariance against the scripted run, no text keys, and fingerprint checks.

### 6.5 Split, owned files, sequencing

**PR-9a — runtime seam, R-19, HTTP adapter, fake gateway.** CI-only; DB lane because `runtime.py` changes. Starts after
PR-8a merges; single writer of `runtime.py` in this window (PR-10 does not touch it; PR-13 comes later).

- Owned (agent_core): `observation.py` (R-19), new `fast_observation.py`, new `local_fast_wire.py`, `interfaces.py`,
  `coordinator.py`, `__init__.py`.
- Owned (case_runtime): `runtime.py` (`_coordinator` flag, fast_failed delivery, `AdapterMode`/inference only).
- Owned (new package): `runtime/packages/local_fast/**`.
- Owned (workspace and API): `runtime/pyproject.toml` (member), `runtime/uv.lock`, `runtime/services/api/pyproject.toml`,
  `api/config.py`.
- Owned (Makefile): `PYTHON_PATHS` and the typecheck list.
- Owned (tests): new `tests/integration/test_local_fast_adapter.py`, `test_fast_failure_fallback.py`,
  `test_fast_observation_renderer.py`, `test_local_fast_config.py`, a fake-gateway helper,
  `tests/fixtures/local-fast-wire/*.json`.
- Owned (docs): `docs/architecture.md`, `docs/development.md`, `CONTEXT.md` (if Q9 = yes), the status file, and the
  log.
- Not owned (escalate): `app.py`, `workflow.py`, `activities.py`, `postgres_repository.py`, `contracts/`,
  `validate_fast_result`, `project_fast_view`, PR-8's gate rules, `ScriptedFastAdapter`, every `ml/` file.

**PR-9b — gateway, conversion, parity, split reports, and the manual run.** No hot file; merges `origin/main` after 9a.
The ml-only parts (G2–G4) can be written in parallel with 9a against the frozen wire module.

- Owned (ml package): new `ml/evaluation/src/proxyloop_evaluation/local_fast/{__init__,trained_view,gateway_core,
  http_server,mlx_adapter_conversion,identity,parity}.py`.
- Owned (scripts): new `scripts/run_local_fast_gateway.py`, `scripts/convert_phase03c_adapter_mlx.py`,
  `scripts/run_phase03c_local_parity.py`, and `scripts/run_fast_slow_split_report.py` (PR-8's; add `--fast-backend`).
- Owned (`ml/serving/`): `README.md`, `phase-03c-cloud-run-01-mlx-attestation.json`.
- Owned (ml tests): new `ml/tests/test_local_fast_gateway.py`, `test_mlx_adapter_conversion.py`,
  `test_local_parity.py`.
- Owned (committed results, after the manual run): `data/experiments/phase-03c/local-parity/parity-report.json`,
  `data/evaluation/fast-slow-split-{distilled,untuned}.json`.
- Owned (repository wiring): `.gitignore` (one line), the `Makefile` targets and ML path lists,
  `scripts/validate_layout.py`.
- Owned (docs): `docs/ml-evidence.md`, `docs/development.md`, the status file, and the log.
- Not owned (escalate): every file in §2.2's frozen set, `ml/pyproject.toml`, `ml/uv.lock`, every `agent_core` file
  (frozen by 9a).

If 9a reviews too large, move the R-19 classifier and `fast_observation.py` into a 9a-0 PR. It is pure `agent_core`
with no hot file, and can go first.

### 6.6 Gates

- **9a**:
  - Focused tests above, plus `test_phase_04a/04b/05a_case_runtime`, `test_model_trace_producer`,
    `test_persisted_claim_and_traces`, `test_direct_mode_command_path`, `test_phase_04d_control_plane_operations`,
    `test_browser_projection_allowlist`.
  - `make lint typecheck test lock-check`, then `make preflight` once. The gated-skip pin is unchanged: no skip-gated
    test is added.
  - DB lane serially: `postgres-check` → `phase05a-check` → `phase06b1-check`.
  - An independent `reviewer`, plus `/security-review` (new network client and failure path).
- **9b**:
  - `make test`, including every existing ml `*-check` and the new checks. `make lock-check` must show `ml/uv.lock`
    unchanged. `make preflight` once.
  - An independent `reviewer` on the converter, the attestation, and the parity statistics.
  - The manual model lane (§6.7) is recorded in the PR log. No DB lane needed.

### 6.7 Manual steps (the root or the user, on this Mac)

Hardware and preconditions:
- Apple silicon, macOS arm64, 48 GB unified memory [O: `hw.memsize` 51,539,607,552, Apple M4 Pro]. At least 32 GB is
  recommended, since the 8B bf16 peak is about 17.1 GB [O, Stage 0].
- The HF cache holds `Qwen/Qwen3-8B-MLX-bf16@6766fd4b` [O]. The PEFT adapter is present with source sha256 `61c29e19…`
  [O: the manifest value; the file hash is to be verified by step 1].
- `uv sync --project ml --extra evaluation` does not change the lock [I].
- Treat the model run as a lane like the DB lane: one run at a time on this machine.

Steps:
1. `make phase03c-mlx-adapter`: convert to the ignored directory and print the attestation. The first run creates the
   attestation JSON; the reviewer checks it before commit.
2. `make phase03c-local-parity`: M1 + M2, 4 arms, up to about 960 generations. It is sequential and resumable.
   Estimated 2–4 h [I].
3. `make local-fast-gateway BACKEND=distilled`, then `make fast-slow-split-report FAST_BACKEND=distilled`. Repeat with
   `untuned`.
4. Optional Browser check: `PROXYLOOP_FAST_BACKEND=distilled make runtime-server` + web, so a person sees that the
   delivered line is (almost surely) the fallback.
5. Record in the PR log: commands, host, package versions, identity and attestation fingerprints, wall times, the
   verdicts, and the explicit not-measured list (p95, capacity, OOM, concurrency, production, fresh-clone reproduction
   of distilled numbers).

---

## 7. Risks

| # | Risk | Notes |
|---|---|---|
| R1 | **Gate collision (D8).** The distilled model's trained style (minor-unit arithmetic, `confirm`/`counter`, 68/240 lines over 600 characters) is almost entirely withheld by gate v1. | ≈ 0/240 held-out outputs pass the approximation [O, P4]. The product demo with `distilled` will show the fallback on nearly every turn. The measurement is honest, but the "distilled Fast dialogue" of DoD item 2 is nominal. Q1. |
| R2 | **Silent untuned load.** `strict=False` could load an untuned model under the distilled label. | Mitigated by L4's self-check and by M1 (a distilled run scoring about 0.54 would expose it). |
| R3 | **Stack divergence (E2).** An unmerged fp32 LoRA on MLX bf16 vs a merged bf16 checkpoint on vLLM. | Greedy paths may split on close rows. M1 measures it. The fallback is `mlx_lm.fuse` (a second ~16 GB artifact), a root decision if the bar fails. |
| R4 | **Latency.** About 10–16 s per distilled call [I]. | Worst-case 512-token outputs time out; the MLX generation cannot be cancelled, so the next call is `503 busy`. B2-8's in-process app lock means one slow Fast call blocks other direct commands for up to 20 s. All are local limits, stated; no p95. |
| R5 | **E1 structural divergence (D3–D5).** | The product cannot express Provider-state signals or applied changes, and the prompt omits the consumer's words. M2 quantifies the observation part; D5 and D6 remain recorded caveats. |
| R6 | **Frozen-byte drift.** | Any accidental edit to `ml/pyproject.toml`, `ml/uv.lock` or a fingerprinted module breaks r4 or 03C checks. `lock-check` and the r4 state test catch it; owned-file lists exclude them. |
| R7 | **Coordinator is shared with ML.** | The new dispatch and capture are opt-in; A15 guards the default. An accidental default flip would move committed bytes. |
| R8 | **Hot file.** | `runtime.py` again, between PR-8a and PR-13; single-writer rule. |
| R9 | **Loopback without authentication.** | Any local process can call the gateway. Acceptable for a local opt-in demo; not a deployment design (deployment is out of scope). |
| R10 | **Reproducibility.** | Distilled numbers are reproducible only on a machine holding the adapter file (git-ignored; publishing it would be a release, a hard limit). A fresh-clone reviewer (DoD 4) can re-run the checks, not the model. |
| R11 | **`uv run` extras.** | `ML_PYTHON_RUN` has no `--extra evaluation`; model targets must add it [I; verify that a plain `uv run --project ml` does not remove `mlx-lm`]. |
| R12 | **PR-8 not yet built.** | This design assumes the frozen PR-8 interfaces (`fast_gate`, `fast_disclosure_rejected`, `FAST_FALLBACK_TEXT`, the split driver). Any change there must be reflected before 9a starts. |

## 8. Questions the root must decide

1. **Q1 — product/scope, not technical.** Accept that distilled Fast mostly delivers the fallback, and report it as the
   headline product number (recommended for PR-9). Or open a separate decision on an "act-to-template" delivery: the
   model chooses the act, a fixed per-act line is shown, and the gate moves to v2 for those templates. That changes what
   the gate allows and what "distilled Fast dialogue" means, so it belongs to the user or root, not this PR.
2. **Q2** Adopt the pre-registered M1 bar (distilled local act agreement ≥ 0.95 and cloud concordance ≥ 0.95). Also
   decide what failing it does. Recommended: it only relabels the backend "stack parity not established" and does not
   remove it. Alternative: failing disables `distilled`.
3. **Q3** Freeze the `agent_core` seam: `ObservingFastAdapter`, the coordinator deriving `SafeObservation`,
   `capture_fast_failures`, `fast_failed`. **Recommend yes.** It is an additive shared interface, and the alternatives
   touch contracts or split the projection.
4. **Q4** Confirm PR-8 answer 9 in this form: only `FastAdapterFailure` is captured (typed, allow-listed), and a
   `FAILED` trace + fallback + applied command follow. `OpenAICompatibleAdapter` and Slow failures are unchanged.
5. **Q5** `adapter_mode` values `local_distilled_candidate` / `local_untuned_baseline` (payload keys unchanged).
   Alternative: keep `model` and put the label only in traces and reports.
6. **Q6** Accept the placement deviation: ml implementation under `proxyloop_evaluation/local_fast/`, and `ml/serving/`
   for the README and the attestation. It is forced by the frozen `ml/pyproject.toml`.
7. **Q7** Commit per-row raw local outputs in the parity report (03C precedent, replayable scoring). The alternative is
   scores only, which loses replay.
8. **Q8** Amend the PR-8 spec §5.2 before 8a starts (`failed` result, `fallback_cause`), or accept a report-schema bump in
   PR-9.
9. **Q9** `CONTEXT.md`: add "Fast Backend" and "Local Opt-in Candidate" in 9a via `domain-modeling`, or defer.
10. **Q10** Timeout default 20 s, cap 25 s. Accept that a Fast call blocks other direct commands under B2-8's app lock
    for its duration (local limit).
11. **Q11 — hard limits.** No credential (loopback, no key), no hosted spend (local only), and no download (the base is
    cached, and `HF_HUB_OFFLINE=1` is enforced). If a machine lacks the cache, downloading ~16 GB of public Apache-2.0
    weights is not on the hard-limit list but is a user-visible resource decision; recommend asking the user first.
    Publishing the adapter or converted weights would be a release: excluded.
12. **Q12** Record D3–D6 (Provider-state defaults, dropped applied changes, the unseen consumer message, strategy text) as
    E1 caveats rather than inventing product signals. **Recommend yes.** Inventing them would be a scope change.
