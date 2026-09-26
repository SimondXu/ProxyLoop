# ADR-0001: Hosted-model relay capabilities and transport

- **Status:** accepted (v2, after the PR #110 review and a second probe)
- **Superseded in part (2026-09-26, user decision):** Decision 2 (world = `gpt-5.4-mini`) is overruled. The world models (Ear, Mouth, SimUser) stay on Gemini as the plan specified, as **Gemini Flash 3.8** called through a separate key the user supplies, not this relay. A later ADR records that route once it is probed. The rest of this ADR stands.
- **Superseded in part by ADR-0005 (world model).**
- **Date:** 2026-09-26
- **Task:** S0-ROOT-04

## Context
Every hosted model (Slow = Claude Sonnet 5, the world's Ear/Mouth/SimUser, the Haiku 4.5 baseline, and TalkAct's `claude-opus-4-8` / `gemini-3.5-flash`) is reached through one third-party, OpenAI-compatible relay. Its host and key live only in the git-ignored `.env`. S0-CON-01, S0-SYS-04/05 and S2-MOD-03 need to know what the relay actually does, so we measured it.

## Evidence
Everything below comes from `scripts/spikes/relay_probe.py` (root-run from the Mac, 2026-09-26). The files are in `docs/decisions/data/`:
- **v1, first pass (kept as the record):** `relay-probe.json` (5 models); `relay-probe-followup.json` (Gemini native schema/functions, `json_object`, the dated Haiku id, an output-heavy cost pass); `relay-cost-input-heavy.json` (the input-heavy cost pass).
- **v2, second pass:**
  - `relay-probe-v2.json` (`--part main`): 9 models in parallel. Each model runs sequentially: basic call → parallel tools → `json_schema` → `json_object` → two plain controls (same texts, no `response_format`) → one long stream (`max_tokens` 300) → 20 TTFT streams → native route.
  - `relay-forced-tool.json` (`--part forced`): 10 calls per model with `tool_choice` naming `classify`, checked by a stdlib schema validator.
  - `relay-cost-input-heavy-v2.json` (`--part cost-input`): 3 calls × `max_tokens` 5 per model, sequential. For the five v1 models the tokens and deltas equal v1 exactly.
- Each file holds the raw response ids and per-call usage. Request ids are there only where the relay returns them: Claude `req_…`, GPT UUIDs, none for Gemini.

| Model id (requested) | Echoed id | Forced tool: ok / schema-valid (n=10) | Parallel tools | `json_schema` prompt tok vs control | Long stream: chunks / tokens / total−TTFT | TTFT p50 (n=20) | $/M in / out |
|---|---|---|---|---|---|---|---|
| `gpt-5.4-mini-2026-03-17` | same | **10 / 10** | yes | **57 vs 23 (honoured)** | 176 / 179 / 0.37 s | 1.35 s | ≤ 0.762 / not measured |
| `gpt-5.4-nano-2026-03-17` | same | 10 / 10 | yes | 57 vs 23 (honoured) | 172 / 175 / 0.36 s | 0.96 s | ≤ 0.204 / not measured |
| `gpt-4.1-mini-2025-04-14` | same | 10 / 10 | yes | 61 vs 24 (honoured) | 172 / 172 / 0.56 s | 1.56 s | ≤ 0.304 / not measured |
| `gpt-5.6-luna-2026-07-09` | same | 10 / 10 | yes | 57 vs 23 (honoured) | 180 / 215 / 0.88 s | 1.18 s | **≤ 95.433** (anomaly) / not measured |
| `claude-sonnet-5` | same | 10 / 10 | yes | 26 vs 26 (dropped) | 99 / 300 / 4.59 s | 2.22 s | 3.00 / 15.00 |
| `claude-haiku-4-5-20251001` | same | 10 / 10 | yes | 23 vs 23 (dropped) | 92 / 300 / 2.98 s | 1.92 s | 1.001 / 5.006 |
| `claude-opus-4-8` | same | 10 / 10 | yes | 26 vs 26 (dropped) | 90 / 300 / 4.15 s | 2.23 s | 5.00 / 25.00 |
| `gemini-3.6-flash` | **`gemini-flash`** | 0 / 0 (8 text replies, 2 × 504) | no | 29 vs 29 (dropped) | 18 / 354 / 7.51 s | 4.42 s | 1.50 / 7.50 |
| `gemini-3.5-flash` | same (two channels) | 0 / 0 (10 text replies) | no | 29 vs 29 (dropped) | 9 / 215 / 1.90 s | 4.83 s | 1.50 / 9.00 |

Reading the table:
- The undated `claude-haiku-4-5` has no channel: v1 got a 503 `model_not_found`.
- **Cost.** Claude/Gemini rates are solved from two equations per model (the v1 output-heavy pass plus the v2 input-heavy pass). GPT input rates are upper bounds (the cents delta divided by prompt tokens, from the input-heavy pass only). **GPT output rates were not measured in this ADR.**
  - `total_usage` is in US cents. Sonnet and Opus solve to 3.00/15.00 and 5.00/25.00, and Haiku to 1.001/5.006.
  - The Gemini rates are *effective* rates, since the relay may bill thinking tokens it does not report.
- **Luna anomaly.** `gpt-5.6-luna` cost 39.8814 cents for 3 calls totalling 4,179 prompt and 12 completion tokens (0 reasoning tokens reported): billed at about $95/M input on this relay. The cause is unknown. `max_tokens`=5 with 4 completion tokens per call rules out hidden reasoning as the explanation (given the relay passes `max_tokens` through). Any foreign use of the key during a model's cost window would land in that model's delta.
- **Structured output.** The prompt-token parity of `json_schema` with its control shows the relay drops the schema for Claude and Gemini; GPT's prompt grows by 34–37 tokens because it is honoured.
  - `json_object` has parity on every model (31 vs 31, and 32 vs 32 for `gpt-4.1-mini`, on GPT, which honours it), so parity is no evidence there. What shows it is dropped for Claude and Gemini is their output: Markdown-fenced or prose, not raw JSON.
  - Haiku answered both JSON prompts with an off-task "I'll complete the requested file change." It did so in the v1 follow-up too; we note it as an anomaly.
- **Forced tool.** 10/10 shows that tool calls come back and validate, not that the relay enforces `tool_choice`: there was one tool and a classify prompt, and n=10 (95 % Clopper–Pearson lower bound ≈ 69 %).
  - **Schema-valid is not correct.** On utterance index 5 ("…a $10 monthly credit for six months."), `gpt-5.4-mini`, Luna and all three Claude models returned `amount_usd` 60, while nano and `gpt-4.1-mini` returned 10. The Ear's numeric cross-check must handle this.
- **Streaming is incremental on every model.** Content arrives in 9–180 chunks for 172–354 tokens.
  - GPT delivers 172–215 tokens in 0.36–0.88 s after the first token. The largest gap on `gpt-5.4-mini` is 0.09 s.
  - Claude spreads its 300 tokens over 2.98–4.59 s. TTFT is not like-for-like across families: Gemini runs with its default thinking on.
- **Echoed id.** This is a string the relay reports, so it cannot detect substitution.
  - `gemini-3.6-flash` echoes `gemini-flash`.
  - Gemini's native `generateContent` returns no id or model at all.
  - `gemini-3.5-flash` is served by two channels: 9 of 20 streams carry timestamp-style ids and a `billing_usage` object, and 11 carry UUID ids without one.
  - The v2 `native_route: true` for GPT ids is the probe's Gemini-route call; it is not a capability we use.
- **Budget.**
  - `/dashboard/billing/subscription` reports `hard_limit_usd: 100`. `total_usage` was 5366.4646 cents before the first v1 pass and 5522.9694 after the last v2 pass. So **$53.66 was used before this probe**, the probe window cost $1.57, and **$44.77 remains**.
  - Of the $1.57, 35.7558 cents fall between v1's end and the v2 main pass. The forced pass ran then and does not read billing.

## Decision
1. **Transport.** Our code uses one route: the OpenAI-compatible `/v1/chat/completions`, streaming with `stream_options.include_usage`. There is no Anthropic- or Gemini-native adapter in `src/`.
2. **World models = `gpt-5.4-mini-2026-03-17` for Ear, Mouth and SimUser.** The Ear and SimUser use forced tool calls; the Mouth is plain text. Reasons (measured):
   - forced tool calls 10/10 with schema-valid arguments 10/10;
   - `json_schema` is honoured (57 vs 23 prompt tokens), so tools and schemas reach the model;
   - real streaming;
   - TTFT p50 of 1.35 s;
   - input at ≤ $0.762/M;
   - it sits outside both agent families (Claude = Slow, teacher and the Haiku baseline; Qwen = Fast), which removes the family-overlap risk the review raised.

   The choice among the GPT candidates is a judgement, and the S2 Ear audit (still stratified by speaker model) is its quality gate. This amends ARCHITECTURE §10.1–§10.2.
3. **Rejected world candidates:**
   - Gemini: no tools or schemas, an echoed-id mismatch, and a native route with no ids.
   - `claude-haiku-4-5-20251001`: it works, but it is the teacher's family and the S4 Fast baseline. It stays the S4 baseline only.
   - `gpt-5.6-luna`: the input-cost anomaly above.
   - `gpt-4.1-mini`: it works, but it is older.
   - `gpt-5.4-nano`: it works and is the fastest. It is kept as a cheaper **config choice** for the Mouth only, if the S2 audit shows no quality loss. It is never a runtime fallback.
4. **One structured-output mechanism.** All structured world and Slow output is a forced tool call (`tool_choice` naming one function), validated against the schema, with failures counted. It works on Claude and GPT (`relay-forced-tool.json`). Our code does not use `response_format`, even though GPT honours it, and does not strip fences or leniently parse prose.
5. **Model ids are exact, dated where available.** Every call records both the requested and the echoed id. `evidence-check` treats a mismatch as a provenance failure. This is a consistency check on relay-reported strings, not proof of the serving model.
6. **TalkAct transport (OPEN_QUESTIONS Q1) is unchanged.** `claude-opus-4-8` works on the native `/v1/messages` route with tool use, and `gemini-3.5-flash` works on native `generateContent` for plain text. Native Gemini streaming (`generate_content_stream`) and `system_instruction` pass-through remain **unverified**; S2-MOD-03 checks them before it runs anchors.
7. **Rate card.** The solved rates are the S0 rate card for `SpendLedger`, which reconciles against `total_usage` deltas at session boundaries. For `gpt-5.4-mini` only the input bound is known; its output rate is unmeasured (see Consequences).

## Consequences
- **S0-CON-01** (no renderer fingerprint impact):
  - the `WorldModels` default is `gpt-5.4-mini-2026-03-17` for `ear`, `mouth` and `simuser`;
  - `ToolRequest` needs a forced `tool_choice`;
  - `LLMCallRecord` keeps the requested and echoed model ids;
  - the world model's reasoning effort is pinned in `SessionConfig`.
- **S0-SYS-04 `llm-smoke`** gates live runs on:
  - forced-tool schema validity on the Slow model and the world model;
  - prompt-token parity with a control (no injected prompt);
  - the echoed id and TTFT;
  - an adversarial control (forced `tool_choice` with a prompt asking for plain text, reply text recorded), with n large enough to test PLAN's 5 % malformed-tool-call threshold;
  - reasoning tokens, recorded per call.
- **Output rate before any spend summary.** `llm-smoke` must measure the output rate of the world model (and nano) with one output-heavy pass, solved against the committed input-heavy pass, before any spend summary. Until then, per-role $/episode for the world is not reportable.
- **Data invalidated:** none.
- **Risks:**
  - **Budget.** About $44.77 is left, which is not enough for S1 teacher-scale runs; the user must top up or supply a key before then.
  - The relay can change without notice, which is why `llm-smoke` exists.
  - The Luna cost is unexplained. Haiku's off-task reply to both JSON prompts must be resolved before Haiku is used as the S4 baseline.
  - GPT's sub-second post-TTFT spread cannot rule out relay-side buffering from the client side.
- **Revisit** if the relay starts honouring Gemini tools or schemas, if a direct provider key appears, or if the S2 audit disputes the world model.
