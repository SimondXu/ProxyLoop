# Repo audit — Lane D3: data factory and model adapters

Reviewer: `reviewer` (Opus, high), read-only; 101 tool uses, ~261K tokens.
Recorded by the root orchestrator from the lane's report; root verification
at the end. Scratch probes under the session scratchpad `laneD3/`. No API
key in the environment; no hosted call; no model download; `qwen_mlx`
exercised only through fakes.

Read completely: `pipeline.py`, `models.py`, `run_phase_02_data_pilot.py`,
`phase-02-annotation-guide.md`, `qwen_mlx.py`, `qwen_spec.py`,
`openai_frontier.py`, `fast_output.py`, `fast_parse.py`, `slow_output.py`,
`legacy_slow_output.py`, `validity_smoke.py`, `phase03b_readiness.py`,
`prepare_phase03b_readiness.py`; six test files; the Phase 02 and 03A1-V
contracts; `docs/ml-evidence.md`; the 03B post-training review `:25-95`.

## 1. Verdict per module

| Module | Verdict | Why |
|---|---|---|
| `ml/data_pipeline/.../pipeline.py` | refactor | Deterministic and byte-reproducible, but the model-facing `learning_content` carries the scenario/family id in every `offer_id` (D3-1); the forbidden-field guard is key-name only; curation is regeneration-equality, so it can only accept rows it generated itself (N1). |
| `models.py` | keep | `rejection_reasons` is a dead field (D3-7). |
| `run_phase_02_data_pilot.py` | keep | Real regeneration diff. |
| `qwen_mlx.py` | keep frozen, do not extend | Fail-closed and attested when `model_path` is given; bare `json.loads` accepts duplicate keys as strict success (D3-5); key-only prompt guard (D3-2); unattested fingerprints when `model_path` is omitted (D3-6). Bound by the r4 execution contract; new adapters wrap, not inherit. |
| `qwen_spec.py` | keep | Identity data plus hashing observer. |
| `openai_frontier.py` | keep with fixes | Budget/cap/credential order correct, `max_retries=0` on every production client, redacted error evidence; prompt allowlist value-blind (D3-2); loose model prefix; unbounded error strings (D3-9). |
| `fast_output.py`, `fast_parse.py` | keep | `fast_parse` well tested (14 fence cases + duplicate keys). |
| `slow_output.py` | keep | Position semantics tested; hash executor-compatible (verified), unlike the runtime copy (B1-4). |
| `legacy_slow_output.py` | keep (replay only) | Only `replay.py` imports it. |
| `validity_smoke.py` | refactor / re-document | Same defect as D2-1 (D3-3). |
| `phase03b_readiness.py` | refactor | `source_manifest_fingerprint` and `source_counts` are constants echoed into the packet (D3-4); `model_input` carries the family id in 12/16 records (D3-1). |

## 2. Findings

### D3-1 — Important — Phase 02 model-facing rows carry the scenario/family id in `offer_id`; the contract's "no scenario labels" clause is enforced by key name only
- `pipeline.py:167-182` copies `offer.offer_id` (`"<family>@1.0::<config>@1.0::offer"`) into `SafeOffer`; `:264` stores `observation.to_dict()` in `learning_content`; `:340-350` `_forbidden_keys` matches keys only.
- Claims: `phase-02-data-factory.md:34-35` ("removes opaque case, offer, and timestamp identifiers"; "The model-facing payload cannot contain scenario labels"), AC6; `phase03b_readiness.py:4-5`.
- Repro (`leak.py`): of 128 accepted rows, `learning_content.observation.offers[].offer_id` contains the family id in 104 and `learning_content.decision.offer_id` in 40. Committed: `data/samples/phase-02-review-sample.json` `records[1].verification.evidence_ref == "add-on-removal@1.0::retention-gated-v1@1.0::confirmation"`; `data/reviews/phase-03b-train-dev-review-packet.json` `records[*].model_input.public_observation.offers[].offer_id` names the family in 12/16 records; the quality report says `accepted_forbidden_field_count: 0`.
- Direction: content-free offer ids at the simulator (D1-1) plus a value-level scan; regenerate the Phase 02 artifacts and the readiness packet.

### D3-2 — Important — both Fast prompt guards are blind to JSON encoded inside string values; with the 03B example views, 20/26 rendered Fast prompts contain the hazard family name
- `openai_frontier.py:817-825` `_assert_prompt_allowlist` and `qwen_mlx.py:608-619` `_assert_safe_keys` recurse Mapping/Sequence and stop at `str`. `VisibleCaseEvent.content` is `HumanText`; `phase03b_experiment.py:261-266` stores `SafeObservation.to_dict()` JSON in that field, and `build_fresh_safe_observation` keeps the family-bearing `offer_id` (26/32 fresh observations).
- Repro (`dup.py`): a view whose latest event `content` is `json.dumps({"expected_action": "decline", "family_id": ...})` passes `build_fast_prompt`. (`b03_leak2.py`): for `build_phase03b_examples()` views, `QwenMLXAdapter.build_prompt(...).rendered` and `build_fast_prompt(...)` contain the family id in 20/26 examples (`"offer_id":"phase-03a1-r2::absent-evidence@2.0::…::offer-r2"`); configuration id in 26/26.
- Blast radius: r2–r5 views use UUID offer ids (0/6 family hits); the committed 03C Stage 0 prompts do **not** contain the family id (6/6 fingerprints match `arm-a-untuned-8b-v3.json`, 0 hits); `phase-03b-qlora-smoke/train.jsonl` 0/20. No committed number is contaminated; the defect is latent in the two builders and in `ValiditySmokeQwenAdapter`, and becomes Blocking the moment a Stage 1 teacher or student prompt is rendered from 03B example views.
- Direction: scan string values (parse JSON-looking strings) in both guards; add a test using a 03B example view.

### D3-3 — Important — the r5 "input parity" prompt also contains the oracle's decision-precedence table (same as D2-1)
- `validity_smoke.py:140-146`; `:84-92`. Repro (`r5_fp2.py`): rebuilding the six Slow requests reproduces all 6/6 committed `prompt_fingerprint`s; the system text contains `transfer_available=true -> escalate`. AC2 satisfied to the letter (no per-episode label); the model was handed the label function.

### D3-4 — Minor — the readiness gate's `source_manifest_fingerprint` and `source_counts` are hard-coded constants (`phase03b_readiness.py:47-55, 335-336`), never compared to the committed Phase 02 manifest. Editing the constant and rewriting the packet still passes `phase03b-readiness-check`.

### D3-5 — Minor — `qwen_mlx.generate` accepts duplicate JSON keys (last wins) as `json_valid=schema_valid=canonical_valid=True` (`qwen_mlx.py:392, 429`). 0 duplicate-key outputs among 726 parseable raw strings in committed reports, so no count affected. File frozen by the r4 execution contract; `fast_parse.parse_fast_json` already rejects duplicates for 03C.

### D3-6 — Minor — metadata reports attestation fingerprints that were never computed when `model_path` is omitted (`qwen_mlx.py:244-254`); all real scripts require `--model-path`, so latent; `test_qwen_mlx_adapter.py:186-188` cements it.

### D3-7 — Minor — pipeline reason-code mislabel (`ValidationError` → `missing_provenance`, hash mismatch → `invalid_verifier_outcome`, `pipeline.py:405-435`); `models.py:82` `rejection_reasons` never populated.

### D3-8 — Minor — three copies of one Slow compiler (`slow_output.py`, `legacy_slow_output.py`, runtime `outputs.py`); tariff literals duplicated in `runner.py:1138-1152`; `run_phase_03a1_validity_smoke.py:242` labels the r5 diagnostic prompt `prompt_version: "phase-03a1-e-frontier-slow-r2-v1"` although the text differs.

### D3-9 — Minor — frontier adapter: `openai_frontier.py:587-590` accepts any `gpt-5.6-terra-*`; `str(exc)` written unbounded into `FrontierCallRecord.error` (latent; committed strings ≤ 104 chars).

### Notes
- N1 Curation is a regeneration-equality check (`pipeline.py:411-418, 439-445`): any row not produced by this pipeline is quarantined as `invalid_verifier_outcome`. The "rejection interface" is proven only against self-mutations.
- N2 `training_ready=False` and `expansion_decision` are constants (`pipeline.py:795-796`); `test_pipeline.py:27` tautological.
- N3 Labels come from the legacy oracle (`pipeline.py:253`); disagreement → quarantine → count drift → `--check` fails (fail-closed for the pilot); for the 88/128 non-accept rows the "verifier" is `action == expected_action` (D1-3).
- N4 The review sample has 3 test-split records; neither the contract nor the guide states it.
- N5 PII detection is 4 regexes + 8 field names; no disclosure or false-completion detector exists in the pipeline (`"PIN 1234"` undetected).
- N6 `FRONTIER_BASE_URL = "https://29qg.com/v1"` receives the key; `max_retries=0` holds for every production construction.
- N7 `actual_cost_usd` = returned usage × hard-coded tariff; `docs/ml-evidence.md:31` "USD 0.117 hosted spend" is that estimate.
- N8 `enable_thinking` / `<think>` handling lives in `phase03c_experiment.py` and `qwen_spec.THINKING_OPEN_TAG` (out of scope).
- N9 `run_phase_03a1_validity_smoke.py:97, 252` use bare `json.loads` with `strict=False` on stored raw output (D2 lane).

## 3. Tables

Leakage in `NormalizedTrajectory` rows (128 accepted): `learning_content.observation.offers[].offer_id` family id in **104**, `learning_content.decision.offer_id` in **40** (model-facing); `provider_message` and `assistant_response_text` 0; lineage fields carry family/split by design (not model-facing); no key named `expected_*`/`split`/`family_id` inside `learning_content`, so the key-only guard passes.

Slow compiler differences: legacy (r1) uses model-supplied ids and `capability_proposals[≤4]`; `slow_output.py` (r2–r5) and runtime `outputs.py` use positions and `next_capability`; all three use the same 3 material terms while the domain uses 6; ml copies hash sorted (executor-compatible, verified), the runtime copy hashes unsorted (B1-4); capability id mapping `f"simulator.{capability}"` matches eval manifests but not the runtime manifest (B1-3).

## 4. Acceptance criteria
Phase 02: AC1–3, 7, 8 supported; AC4 supported as stated but weak (self-mutation probes); AC5 tautological (regeneration equality); **AC6 forbidden-field claim not supported at value level (D3-1)**; AC9 constants; AC10/11 not run/checked here.
03A1-V: AC3, 4, 5, 6 supported; AC1 partial (no test asserts absence from the r4 prompt); **AC2 letter yes, spirit no (D3-3)**; recorded outcome "5/6 after parity" attribution unsupported.

## 5. Test quality
Load-bearing: `test_pipeline.py` (reorder determinism, forged verification, PII injection), `test_qwen_mlx_adapter.py` (fenced/extra-field/action_intent rejection, attestation), `test_openai_frontier_adapter.py` (creds, budget-before-call, `max_retries=0`, cost math), `test_slow_output_erratum.py`, `test_validity_smoke.py` tamper rejection, `test_phase03c_experiment.py` fast_parse. Tautological/gaps: counts and `training_ready` asserted against constants; forbidden-field tests key-only; no value-level leakage test; no verifier-disagreement quarantine test; duplicate keys untested in qwen_mlx; prompt-leak tests use views with no events; readiness constants asserted against themselves.

## 6. Checks
Run: six `ml/tests` files → 69 passed; `make data-pilot-check` pass; `make phase03b-readiness-check` pass; ten scratch probes. Not run: `make preflight/lint/typecheck` (root baseline), real MLX, hosted calls.

## 7. Open questions
1. D3-2/D1-1: does Stage 1a/1b render any teacher or student prompt from `build_phase03b_examples()` views? If yes, Blocking for that stage.
2. D3-3: reword `docs/ml-evidence.md:37-38` now, or authorise a parity-only re-run of the six episodes?
3. N1: is the Data Factory meant to accept non-self-generated rows? If yes, `curate_candidates` needs a real curation path.
4. D3-5: does the r4 execution contract permit a parse fix in `qwen_mlx.py`, or must every new adapter wrap it?

Lane recommendation: **Request Changes**.

## Root verification (2026-09-21)

Root read the committed `phase-03b-train-dev-review-packet.json`
(`model_input` carries a scenario id in 12/16 records) and the review sample
(`evidence_ref` carries the scenario id), and re-ran `b03_leak2.py` (20/26
03B example views render the family id into both Fast prompt builders) and
`c03_dev.py` (03C Stage 0 prompts: 0 family hits, fingerprints match the
committed artifact).

| Id | Verdict | Root note |
|---|---|---|
| D3-1 | confirmed, Important | Same root cause as D1-1; the Phase 02 "zero forbidden fields" number is a key-name measurement. |
| D3-2 | confirmed, Important; **Blocking for Stage 1b/1c if any prompt is rendered from 03B example views** | 03C Stage 0 is clean; the Stage 1 teacher pipeline must not reuse `build_phase03b_examples()`. |
| D3-3 | confirmed (duplicate of D2-1, Blocking as an evidence claim there) | — |
| D3-4 … D3-9 | accepted as reported | Probes under `laneD3/`. |
