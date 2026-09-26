# ADR-0001: Hosted-model relay capabilities and transport

- **Status:** accepted
- **Date:** 2026-09-26
- **Task:** S0-ROOT-04

## Context
Every hosted model (Slow = Claude Sonnet 5, the world's Ear/Mouth/SimUser, the Haiku 4.5 baseline, and TalkAct's `claude-opus-4-8` / `gemini-3.5-flash`) is reached through one third-party, OpenAI-compatible relay. Its host and key live only in the git-ignored `.env` and are never committed. S0-SYS-04 (LLM adapters), S0-SYS-05 (world) and S2-MOD-03 (TalkAct anchors) need to know what the relay actually supports, so we measured it instead of assuming it.

## Evidence
All artefacts come from `uv run --no-project scripts/spikes/relay_probe.py` (root-run, 2026-09-26, from the Mac):
- `docs/decisions/data/relay-probe.json`: the main pass. Five models in parallel, each run sequentially: basic call, 20 streaming calls (TTFT), parallel tool calls, JSON-schema output, and the native route.
- `docs/decisions/data/relay-probe-followup.json`: Gemini native `response_schema` and function calling; `json_object` mode; the dated Haiku id; output-heavy cost.
- `docs/decisions/data/relay-cost-input-heavy.json`: input-heavy cost. With the output-heavy pass it gives two equations per model, solved for $/M input and $/M output.

Each file holds the raw response ids, request ids (Anthropic models) and usage per call.

| Model id (requested) | Available | Echoed model | Stream + usage | Tool calls (parallel) | `response_format` json_schema / json_object | Native route | TTFT p50, Mac, n=20 | $/M in / out (solved) |
|---|---|---|---|---|---|---|---|---|
| `claude-sonnet-5` | yes | `claude-sonnet-5` | yes | yes (2/2) | **ignored** / ignored (fenced text) | `/v1/messages`: yes, incl. tool_use | 2.21 s | 3.00 / 15.00 |
| `claude-haiku-4-5` | **no** (503 `model_not_found`, no channel) | — | — | — | — | no | — | — |
| `claude-haiku-4-5-20251001` | yes | `claude-haiku-4-5-20251001` | yes | yes (2/2) | ignored | `/v1/messages`: yes, incl. tool_use | 2.14 s | 1.00 / 5.01 |
| `gemini-3.6-flash` | yes | **`gemini-flash`** | yes | **no: tools dropped** (26 prompt tokens, 0 calls) | ignored / ignored | `generateContent`: text only; `response_schema` and function calling **ignored** | 4.24 s | 1.50 / 7.50 |
| `claude-opus-4-8` | yes | `claude-opus-4-8` | yes | yes (2/2) | ignored | `/v1/messages`: yes, incl. tool_use | 2.21 s | 5.00 / 25.00 |
| `gemini-3.5-flash` | yes | `gemini-3.5-flash` | yes | no (tools dropped) | ignored / ignored | `generateContent`: text only; schema and functions ignored | 4.56 s | 1.50 / 9.00 |

- **Billing.** `GET /v1/dashboard/billing/usage` returns `total_usage` in US cents. The solved Claude prices equal the public list prices to the cent, so the unit is confirmed. `/dashboard/billing/subscription` reports `hard_limit_usd: 100`, and the key's `total_usage` went from 5366.46 to 5383.06 cents across the three probe passes. So **about $53.7 of the $100 key limit had already been used before S0**, this probe cost $0.17, and about $46.2 remains on the key.
- The Gemini "cost" includes whatever thinking tokens the relay bills but does not report, so the Gemini rates are effective rates, not list prices.

## Decision
1. **One transport for our code:** the OpenAI-compatible `/v1/chat/completions` route, streaming with `stream_options.include_usage`. Slow (Sonnet 5) uses OpenAI-style tool calls; parallel calls work. We add no Anthropic-native adapter to `src/`.
2. **Never rely on `response_format`.** The relay accepts `json_schema` and `json_object` and silently ignores both. Structured output from a hosted model is a **forced tool call** (`tool_choice` naming one function) on a Claude model, validated against the schema, with failures counted. Code must not strip Markdown fences or otherwise leniently parse prose into JSON.
3. **The world's structured roles move from Gemini to Haiku.** ARCHITECTURE §10 specified `gemini-3.6-flash` with a JSON schema for the Ear and JSON `{text, revealed}` for SimUser. Through this relay Gemini gets neither schemas nor tools, echoes a different model id (`gemini-flash`), and is about 2 s slower to first token. So the **Ear, SimUser and Mouth use `claude-haiku-4-5-20251001`**: the Ear and SimUser through forced tool calls with a closed enum or schema, and the Mouth as plain text. This amends ARCHITECTURE §10.1–§10.2. The world model id is a `SessionConfig` value, so it can be swapped later without a second path.
4. **Model ids are exact.** Use the dated id `claude-haiku-4-5-20251001` everywhere, including the S4 Haiku baseline. The undated alias has no channel. Every call records the echoed model. `evidence-check` compares it with the requested id and treats a mismatch as a provenance failure, not a warning.
5. **TalkAct transport (OPEN_QUESTIONS Q1).** No translation proxy and no direct provider keys are needed:
   - `claude-opus-4-8` works on the Anthropic-native `/v1/messages` route, including tool use, so TalkAct's `anthropic` SDK runs unmodified with its base URL pointed at the relay;
   - `gemini-3.5-flash` works on the native `generateContent` route for plain text, which is all TalkAct's Gemini paths use (`fast_agent._generate_gemini`, `simuser`).
   - **Not yet verified:** native streaming (`generate_content_stream`) and `system_instruction` pass-through on the Gemini route. S2-MOD-03 checks both before it runs anchors, and states them in its own ADR.
6. **Rate card.** The solved prices above are the S0 rate card for `SpendLedger` (S0-SYS-04). The ledger reconciles against `total_usage` deltas at session boundaries, since the relay's own counter is the truth for spend.

## Consequences
- **Contract / fingerprint impact:** none on the renderer. S0-CON-01 must give `SessionConfig` per-role world model ids, defaulting to `claude-haiku-4-5-20251001`. The `LLMClient` needs a forced-tool structured-output request (`ToolRequest` with a required tool).
- **Data invalidated:** none (no data exists yet).
- **Risks:**
  - **Budget.** At about $46 left on the key, S1's teacher runs and S3's data generation will exceed it. The user must top up the key, or supply another one, before S1 teacher-scale runs; the S0 spend summary will show the projection.
  - Haiku as both a world model and the S4 Fast baseline could flatter the Haiku baseline (same-family rep). S4 reports this as a limitation, or swaps the world model through `SessionConfig`.
  - Relay behaviour can change without notice. `make llm-smoke` (S0-SYS-04) re-checks tool calls, the echoed model and TTFT, and a regression there blocks live runs.
- **Revisit** if the relay starts honouring Gemini schemas or tools, or if a direct Anthropic or Google key becomes available.
