# ADR-0027: Slow on Claude Sonnet 5.5 over the Anthropic API

- **Status:** accepted (user decision 2026-10-11)
- **Date:** 2026-10-11
- **Task:** S1-SYS-99

## Context
Smokes #4–#9 (2026-09-29) stopped on Slow's judgement, not on mechanism: Gemini 3.8 Flash did not record identity facts the user gave and did not use a lever its status bar offered. In those runs its median reasoning tokens were 0 at effort low, medium and high (one high run reasoned ~1,400 tokens per step and was cut off at 1,500 max tokens). A Slow run is ~35 steps of ~5.5k input tokens and ~60 output tokens; the median step took ~2.1 s. Independent benchmarks (Artificial Analysis, read 2026-10-11) rank Sonnet 5.5 first among the candidates on AutomationBench-AA (71.8 % vs Gemini 3.8 Flash 59.9 %), with ~0.7–1.05 s to first token at low/medium effort. The user's Max plan includes a monthly Anthropic API credit (from 2026-10-07), spendable only on the Claude API, not through OpenRouter. Sources and the full comparison: the research notes `llm-slow-planner-model-comparison` and `claude-max-monthly-api-credits` in the user's vault.

## Decision
1. **Model (user decision):** Slow runs `claude-sonnet-5-5` on a new endpoint `anthropic` (Anthropic's native `/v1/messages`), billed to the monthly credit. Contract change: `Endpoint` gains `"anthropic"` (`contract/llm.py`); no profile fingerprint changes (only `tests/contract/snapshots/manifest.schema.json`). `make pull-through` is not needed: no Fast prompt changes.
2. **Adapter:** `proxyloop.llm.anthropic.AnthropicClient` on the shared httpx base (`llm.http`): the same records, the same single pre-first-token connect retry, the same `LLMUnavailable`. It serves tool calls only. Thinking blocks are never replayed (`ChatMessage` carries none, and Slow's windowed context would fail the history-editing check). No `fallbacks` parameter is sent (AGENTS rule 6). Prompt caching uses the request-level `cache_control`.
3. **Tool choice:** Sonnet 5.5 refuses a forced tool (HTTP 400). Slow now sends `tool_choice` none and relies on its system prompt ("Every turn, call `act` once"). A step without a tool call is counted as before (`_NO_TOOL`), never retried. The adapter passes a forced `tool_choice` through unchanged, so a forcing caller fails loudly.
4. **Effort:** the CLI pins `medium` for an Anthropic Slow (`ANTHROPIC_SLOW_EFFORT`; Anthropic's suggested start for multistep tool use). `none` maps to `thinking: between_tools`, `low`/`medium`/`high` to adaptive thinking at that effort, and `minimal` is refused. A different level is the user's decision.
5. **Spend:** `ANTHROPIC_RATES` prices input at the 5-minute cache-write rate ($2.50/M) and output at $10/M. `Usage` has no cache split, so this is an upper bound. The session cap ($2) still applies, although the credit pays.
6. **Secrets:** `PL_ANTHROPIC_BASE_URL` (`https://api.anthropic.com`) and `PL_ANTHROPIC_API_KEY`, set by the user from the Console organisation linked to the credit.

## Consequences
- Slow is now a different family from the world (Gemini) and the teacher (DeepSeek).
- `slow_fp` changes by design: `slow/` code changed.
- The relay-only request snapshot changes only in `tool_choice`.
- Gemini can still be selected as Slow with `--slow-endpoint openrouter`; it now also runs without a forced tool.
- Not yet proven: the change is verified only offline (mock transport). The first live runs (3, effort medium, `x-out-of-envelope-approval`) must show infra-clean steps, a tool call on most steps, and step latency under the rep's 6 s silence.
