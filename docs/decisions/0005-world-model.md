# ADR-0005: World model = `gemini-3.8-flash` via TeamRouter

- **Status:** accepted
- **Date:** 2026-09-26
- **Task:** S0-ROOT-08
- **Supersedes in part:** ADR-0001 Decision 2 (world = `gpt-5.4-mini-2026-03-17`).

## Context
The world roles (Ear, Mouth, SimUser) need a hosted model outside both agent families (Claude = Slow, teacher and the Haiku baseline; Qwen = Fast). ADR-0001 chose `gpt-5.4-mini` on the relay. On 2026-09-26 the user overruled that and kept the world on Gemini, as the plan specified. The model is Gemini Flash 3.8, reached through TeamRouter with a separate key the user supplies, not through the relay. On the relay, Gemini had no working tools or schemas (ADR-0001), so we probed the TeamRouter route with the same script before recording it.

## Decision
1. **World models.** Ear, Mouth and SimUser use `gemini-3.8-flash` with `ModelRef.endpoint = "teamrouter"` (user decision, 2026-09-26). ARCHITECTURE §10 and PLAN S0-SYS-05 say so.
2. **Transport.** One route: the OpenAI-compatible `/v1/chat/completions`, as in ADR-0001 Decision 1. There is no Gemini-native adapter.
3. **Structured output** is a forced tool call (`tool_choice` naming one function), validated against the schema, with failures counted (ADR-0001 Decision 4). Our code does not use `response_format`, does not strip fences and does not parse prose leniently.
4. **Exact ids.** Every call records the requested and the echoed id (ADR-0001 Decision 5).

## Evidence
Both files come from `scripts/spikes/relay_probe.py` in dotenv mode, run by the root from the Mac on 2026-09-26. The key file was passed by absolute path and never copied, and the host and key are redacted.
- `docs/decisions/data/teamrouter-probe-forced.json` (`--part forced --models gemini-3.8-flash --forced-n 10 --forced-max-tokens <forced_max_tokens>`):
  - `summary.gemini-3.8-flash.forced_ok_rate` and `schema_valid_rate`: the forced tool call comes back, and its arguments are checked by the stdlib validator;
  - `summary.gemini-3.8-flash.reasoning_tokens_p50` and `reasoning_tokens_n`: the reasoning tokens per forced call;
  - `results.gemini-3.8-flash.calls[].schema_errors` shows which fields failed; `calls[].args` shows the values.
- `docs/decisions/data/teamrouter-probe-main.json` (`--models gemini-3.8-flash --ttft-n 10 --stream-max-tokens <ttft_stream_max_tokens>`):
  - `summary.gemini-3.8-flash.echoed_model`;
  - `tool_calls` and `parallel_tool_calls` (unlike the relay's Gemini, per ADR-0001);
  - `json_schema`, `json_object` and `json_prompt_tokens`: `json_schema` is not used (Decision 3);
  - `streaming`, `streaming_usage`, `ttft_p50_s` and `ttft_n_ok`;
  - `streams_reasoning.reasoning_tokens_p50`;
  - `balance_before`, `balance_after` and `results.gemini-3.8-flash.native` are `skipped`: this endpoint has no relay billing or native route.

## Consequences
- **Contract / fingerprint impact:** none. `Endpoint` already includes `"teamrouter"`, and `WorldModels` already requires a pinned `reasoning_effort` for each role.
- **Data invalidated:** none.
- **Migration:** S0-SYS-04 resolves the `teamrouter` endpoint from the environment. S0-SYS-05 configures the three world roles with it.
- **Risks (for S0-SYS-05 to implement and test):**
  - **Schema-invalid Ear output.** `schema_valid_rate` is below 1 in this run, so the Ear's closed-enum output can be schema-invalid. The world must count a schema-invalid Ear call as an error event, then fail or regenerate under ARCHITECTURE §10's rules. It must never silently coerce the output. Schema-valid is also not correct: the numeric cross-check in ARCHITECTURE §10 still applies (compare `calls[].args` with the utterances).
  - **Reasoning by default.** `reasoning_tokens_p50` is well above zero, and the probe ran with the provider's default effort. The world's `max_tokens` must leave room for reasoning, and each role's `ModelRef.reasoning_effort` must be set explicitly, as the contract requires. S0-SYS-05 picks the value with a probe; this ADR does not assume one.
  - **Latency.** TTFT (`ttft_p50_s`) is dominated by reasoning. The world's latency counts against the counterparty's patience clock, so S0-SYS-05 should measure whether a lower `reasoning_effort` keeps Ear accuracy.
  - **Provenance limits.** The echoed id is a string TeamRouter reports and cannot detect model substitution. Only the basic call carries a request id.
  - **Cost.** This probe does not measure the world's cost; TeamRouter has no billing endpoint the probe reads. Per-role $/episode for the world must be measured before any spend summary (PLAN §0.8).
- **Revisit** if the S2 Ear audit disputes the model, if TeamRouter changes behaviour (checked by `llm-smoke`), or if the user changes the world model.
