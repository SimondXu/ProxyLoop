# ADR-0010: Model roles: Slow and integration Fast via TeamRouter, reasoning efforts

- **Status:** proposed (each setting below is the user's decision, pending; development uses the interim values meanwhile)
- **Date:** 2026-09-26
- **Task:** S0-ROOT-12

## Context
On 2026-09-26 the user decided:
- **Slow** moves to `gemini-3.8-flash` via TeamRouter (it was `claude-sonnet-5` via the relay).
- **Integration/development Fast** is `gpt-6-luna` via TeamRouter, as condition C5 (EVAL §4.1).
- **Qwen3.5-9B stays the research Fast.** Qwen claims still need Qwen@vllm bundles with P3 = pass (S1-SYS-14).

Before the switch we probed the roles cheaply. The probe was an offline replay of the recorded run in `source_run_id` (the failed S0-ROOT-05 smoke). It went through production code only: `make_client` on `teamrouter`, `render_messages` + `parse_turn`, Slow's `act` tool, the Ear's recorded `classify` tool and `check_act`. The script is `scripts/mod/probe_roles.py` at the `git_sha` recorded in each JSON, and the main root ran it. The metric definitions are in the script: `valid_rate` and `parse_issue_rate` are over every call (`n`), so a rejected call counts as a failure; `*_answered` counts answered calls only; `tokens` holds the exact usage totals over every attempt.

## Decision
1. **Slow `reasoning_effort` = `low`.** Its validity equals the default arm's, it uses fewer tokens and its tail is shorter. Interim: `low`.
2. **World (Ear, Mouth, SimUser) `reasoning_effort` stays `low`.** This probe confirms the provisional value (`WORLD_EFFORT` in `cli.py`, per ADR-0005, which left the value to a probe). The probe measured only the Ear; the Mouth and SimUser share its setting. Interim: `low`.
3. **C5 (Luna) pins `reasoning_effort` and the model id.**
   - Effort: prefer the lowest setting Luna accepts (`minimal` or `none`, still to be probed). This keeps the shared Fast sampling identical across conditions: no C5-specific sampling (S1-MOD-01). Interim: the CLI's provisional `HOSTED_FAST_EFFORT` (`low`, S0-SYS-08). This probe did not test that value: it ran Luna at the provider default.
   - Raising `max_tokens` only for C5 would be a condition-specific sampling difference. It needs the user's explicit approval and a label.
   - Model id: pin the dated id echoed in `probe-roles-fast.json` `arms.default.served_model_echo` in the registry (exact ids, never aliases; ADR-0001 Decision 5), after checking that TeamRouter accepts it.
4. **Unresolved:** the cause of the user-lane HTTP 400s. Re-check after the effort is pinned.
5. **Follow-up probe.** A small follow-up probe will test Luna's effort settings and the dated id. Its results will be appended to this ADR.

## Evidence
The files are in `docs/decisions/data/`: `probe-roles-slow.json`, `probe-roles-ear.json` and `probe-roles-fast.json`, plus `probe-roles-ear-attempt1.json` and `probe-roles-ear-attempt2.json`. The attempt files are two Ear runs that a `ConnectTimeout` aborted (`complete`, `aborted`); they are kept because they are real spend. The command lines are not recorded in the JSONs; `selection` and `arms.*.n` record each sample. Slow's sample is smaller than the task block planned.
- **Slow** (`probe-roles-slow.json`, arms `low` and `default`):
  - Every call in both arms is valid, with one `act` call per response (`arms.*.valid_rate`, `calls_per_response`, `tool_call_valid_rate_answered`).
  - The failure we feared did not occur: Gemini did not reject replayed tool history that has no thought signatures (`n_rejected`, `finish_reasons`).
  - Compare ADR-0005, where Gemini's forced-tool `schema_valid_rate` on a simpler schema was below 1. That is a different schema and validator, and both samples are small.
  - Reasoning is a long tail: `reasoning_tokens_p50` is far below `reasoning_tokens_p95`. That tail drives the latency tail (`latency_ms_p50` vs `latency_ms_p95`).
  - `default` spends far more reasoning and completion tokens than `low` (`arms.*.tokens.reasoning`, `.completion`), and its latency tail is longer.
- **Ear** (`probe-roles-ear.json`, arms `none`, `minimal`, `low` and `default`):
  - Every arm is valid on every request (`valid_rate`).
  - `low` has the tightest latency tail (`latency_ms_p95`), the smallest reasoning tail (`reasoning_tokens_p95`) and the least total reasoning (`tokens.reasoning`). `minimal` has the lowest reasoning median (`reasoning_tokens_p50`).
  - `agreement_with_default` is slightly lower for `low` than for `none` and `minimal`. At this `agreement_n` the difference is a single request, and agreement with `default` is not accuracy. The S2 Ear audit is the accuracy gate.
- **Fast / Luna** (`probe-roles-fast.json`, `arms.default`, the provider's default effort):
  - Some requests were rejected with a generic upstream HTTP 400 (`n_rejected`, and `rejections` with trace ids). All of them are user-lane views (`calls[].source`), and they are also the first calls of the part, so lane and time are confounded. The cause is unknown.
  - Luna reasons by default (`reasoning_tokens_p50`, `_p95`). Under the shared Fast `max_tokens`, several turns end with `finish_reasons.length`, their reasoning uses the whole budget (`calls[].usage.reasoning_tokens` equals `completion_tokens`), and they parse as an empty turn (`issues_by_reason.empty_turn`). One further `length` turn produced text; its truncation is not a counted ParseIssue.
  - `parse_issue_rate` (over `n`, rejections included) is well above `parse_issue_rate_answered`.
  - Latency (`latency.*`) is relay-measured, and TTFT includes reasoning (`ttft_includes_reasoning`). Empty turns have no TTFT (`ttft_n` < `n_ok`). Rejected calls waited long before their 400 (`calls[].latency_ms`) and are outside the percentiles. None of this is ever a headline comparison with self-hosted Qwen (EVAL §4.1). The user noted on 2026-09-26 that relay latency is expected to be high.
  - **The echoed id is dated** (`arms.default.served_model_echo`), not the requested `gpt-6-luna` (`arms.default.model_id`). `evidence-check` requires the echo to equal the `model_id`, so C5 bundles cannot pass `--claim` until the registry pins the dated id (Decision 3).
- **Spend.** Exact token totals per part are in `arms.*.tokens`. The attempt files add the aborted Ear runs, and `records_without_usage` counts the calls that reported no usage.
  - **The price was not measured.** TeamRouter exposes no balance or billing endpoint, and `/v1/models` lists no prices; the user reads the charge from the TeamRouter dashboard.
  - The ledger therefore still cannot price TeamRouter (S1-SYS-14).

## Consequences
- **Contract / fingerprint impact:** none. `ModelRef.reasoning_effort` and the `teamrouter` endpoint already exist.
- **Data invalidated:** none.
- **Migration:** S0-SYS-08's `--slow-effort` and the world efforts take the interim values. The C5 registry entry (S1-MOD-01) waits for the follow-up probe before it pins its effort and id.
- **Risks and concerns carried:**
  - **Model-family separation (EVAL §9.7).** Slow and the world are both Gemini, so their errors can correlate. Before the S2 Ear audit, the user either chooses a non-Gemini world model or accepts the risk.
  - **The teacher stays `claude-sonnet-5`.**
  - **Slow input sizes are an upper bound.** Bounded Slow context (ADR-0009) will cut Slow input, and this probe ran on the unbounded context.
  - **The Slow latency tail from reasoning remains, even at `low`.** Slow's whole-call timeout must cover it.
  - The samples are small, and the Ear efforts differ by single requests.
- **Revisit** if a later Slow smoke shows invalid `act` calls or runaway reasoning, if the S2 Ear audit disputes the world effort, or if the follow-up probe finds that Luna rejects the pinned effort or id.
