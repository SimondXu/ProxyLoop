# Phase 03C Stage 1b Preflight — teacher pipeline and pilot

Date: 2026-09-21

## Activation evidence

- Continuation of the user's 2026-09-21 whole-flow authorization; the user
  also directed the teacher path to the third-party relay ("尝试 call 那个
  api") after asking whether a Gemini flash model would be a better teacher.
- Stage 1a merged as PR #34 (`027bc81`). Branch
  `feat/phase-03c-stage1b-teacher-pipeline`; `harness/status.toml`
  `in_progress`, `active_product_phase = "03C-stage1b"`.

## Observed state

- Relay `https://29qg.com/v1` (`openai_frontier.FRONTIER_BASE_URL`), key
  env `PROXYLOOP_FRONTIER_API_KEY`; the key exists only in the git-ignored,
  untracked `.env` (`key:value` lines). `/v1/models` (read-only) lists
  `gemini-3.6-flash`, `gemini-3.5-flash`, `claude-sonnet-5`,
  `claude-opus-5`, `gpt-5.6-terra`; no "gemini 3.8". Relay prices are not
  exposed by the API.
- `openai_frontier.py` is r4-frozen; it is imported, not edited.
- Stage 1a delivered `build_parameterised_scenarios`, `harvest_positions`
  (2 positions), and the invariant suite over seeds 1..1000.

## Frozen decisions

1. Teacher adapter `RelayTeacherAdapter` on the relay seam (OpenAI-compatible
   chat completions, `response_format={"type": "json_object"}`, temperature
   0.7, `max_retries=0`, 60 s timeout, sanitized errors, key only from the
   env var). Model id is a parameter; the pilot runs `gemini-3.6-flash` and
   `claude-sonnet-5` and selects by F2. No Anthropic-SDK adapter.
2. The teacher receives exactly `Phase03CQwenAdapter.build_prompt(view)`
   (system + user), so training rows, the local Fast model, and Stage 3 arms
   share one prompt builder (contract risk 4).
3. Budget: one shared `TeacherLedger` across models, `usd_ceiling` 15.0 for
   the pilot, enforced before every call with a worst-case per-call
   estimate; rates from `ml/configs/teacher-rates.json` (placeholder upper
   bounds, user-maintained) — every USD figure is an accounted estimate.
4. Prompt set: 10 train families × 2 configurations × seeds 1..100 × 2
   positions = 4,000 train rows; dev = seeds 900..909 (400 rows, the
   contract's "~400"); dev/test families never sampled. Manifest stores
   metadata and fingerprints only (`parameters_by_seed` table), ~1.5 MB.
5. Filters F1–F5 in order, first failure wins: F1 strict JSON + schema (no
   tolerant parsing for training data); F2 target agreement (dialogue act,
   the full `reasoner_request` incl. `reason_code` — consistent with
   `evaluate_fast_result_v3` — null action_intent, `not_done`); F3 verifier replay through
   the multi-turn environment (the `runner_v2` coordinator path needs a Slow
   adapter; the environment replay is the deterministic equivalent for a
   Fast-only sample — recorded as a deviation for the reviewer); F4
   detectors incl. `fact_updates` provenance; F5 optional second family,
   `null` when absent. Dedup by lexical fingerprint and content hash, ≤ 2
   per prompt.
6. Pilot: 200 prompts (20 per train family, deterministic selection),
   k = 3, per model; Go if F1 ≥ 95%, F1∧F2 ≥ 60%, F1–F4 ≥ 40%; Stop if F2 <
   40%; otherwise Hold. The Go/Stop thresholds use the contract's literal
   F2 (dialogue act + `needed`, total-sample denominator,
   `f2_act_needed_rate`); the full-`reasoner_request` rate (`f2_rate`) and
   the F1-conditional rate are reported alongside. Raw pilot sample JSONL,
   ledger, report, and per-model curation artifacts are committed under
   `data/experiments/phase-03c/teacher/`; only accepted training JSONL is
   git-ignored. Before the 200-prompt run a ≤ 20-call transport smoke in a
   separate out-dir checks `json_object`, `usage`, and `finish_reason`
   behaviour on the relay.
7. Stage 1c (full generation, ≤ USD 150) starts only after the pilot Go and
   is a separate bounded change.

## Decisions added after the transport smoke (2026-09-21)

- Transport smoke (10 prompts × k=1 per model, separate out-dir, ≈ USD 0.2):
  `claude-sonnet-5` returned strict JSON 10/10 with usage and
  `finish_reason`; every Gemini id tried on the relay (`gemini-3.6-flash`,
  `gemini-3.5-flash`, `gemini-3-flash-preview`) ignored
  `response_format=json_object` and returned markdown-fenced or interleaved
  text (3.6-flash also hit the 512-token cap on 10/10);
  `gemini-2.5-flash-nothinking` is `model_not_found` (503). Under the
  contract's F1 rule (no tolerant parsing for training data) the Gemini
  path is not a usable teacher on this relay; it stays in the pilot only as
  recorded evidence.
- With the v3 prompt, Sonnet agreed with the oracle's dialogue act on 5/10
  but with the target `reasoner_request` on 1/10: the v3 prompt never
  states the house convention (acceptable offer → `confirm` +
  `needed: true` + `offer_candidate_requires_slow_review`, etc.). The
  contract's Stop rule prescribes fixing the prompt, so prompt version
  **v4** = v3 + one `DECISION_CONVENTION` block (the oracle's rule order,
  stated in the prompt) was added additively; v3 and the Stage 0 artifacts
  are untouched. The v4 smoke: Sonnet F1 10/10, F2 8/10, F1–F4 7/10.
  Every Stage 1b/1c/2/3 prompt uses v4; the untuned 8B/4B smokes are rerun
  with v4 (`arm-a-untuned-{8b,4b}-v4.json`) so Stage 3's untuned arm has a
  v4 baseline. Prompt-only-is-enough remains a first-class outcome.
