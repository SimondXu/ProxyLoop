# ADR-0019: Contract: record the sampling actually sent (`LLMCallRecord.sampling_sent`)

- **Status:** accepted (root decision under §0.5a, 2026-09-27, #155 review D6, option (a); placement and the `llm/http.py` grant: root, 2026-09-27)
- **Date:** 2026-09-27
- **Task:** S1-CON-05

## Context
- **Sampling with no effect.** Hosted Fast in development is `openai/gpt-6-luna` on OpenRouter (ADR-0011). OpenRouter's `GET /api/v1/models` lists, for that model, the `supported_parameters` it honours; fetched 2026-09-27, the list has no `temperature` and no `top_p`. `ChatClient` still sent both, and nothing recorded whether they took effect, so a bundle could imply that a run used sampling the provider ignored.
- **Where to record it.** The task first named the manifest schema. The manifest has no per-call data: its only sampling is `cfg.fast_sampling` (`SessionConfig`, frozen, and it holds the *requested* values), and `RoleModel` is per role and filled once by the kernel. Sampling is a per-call fact (a `ToolRequest` sets its own `temperature`), and every call already writes one `LLMCallRecord`, the `llm.call` payload. Options: a field on `RoleModel` filled by the kernel (rejected: per role, not per call, and not the adapter's own knowledge); a new field on `Sampling` (rejected: it would change a frozen type and `cfg_hash`); a field on `LLMCallRecord` (chosen).

## Decision
- `SamplingKey = Literal["temperature", "top_p", "seed"]` and `LLMCallRecord.sampling_sent: dict[SamplingKey, float | int] | None = None`. A dict lists exactly the sampling keys that went into the HTTP body, with their values. `None` means that none were sent, so the provider default applied. An empty dict is refused, so there is one spelling for "none sent".
- `llm/http.py` fills the field in `HTTPAdapter._call` from the request body itself, for every attempt's record (success, failure, cancel). A record therefore can never claim sampling that was not sent.
- `llm/relay.py` holds a static table, `UNSUPPORTED`, keyed by (endpoint, model id), with the OpenRouter source cited in a comment. The only entry is `("openrouter", "openai/gpt-6-luna") → {temperature, top_p}`. For a listed model those keys are left out of the body. Unlisted models behave as before. No parameter is ever added that was not requested; there is no retry and no fallback (AGENTS rules 6, 12).
- `llm/vllm.py` is unchanged: it sends `temperature` and `top_p` (and `seed` when given), and the record lists them.

## Evidence
- `tests/llm/test_sampling_sent.py`: for Luna, neither `temperature` nor `top_p` is in the body, and the record says `None` (or `{"seed": 7}` when a seed is sent). Unlisted models and vLLM record exactly their body's keys, and a failed attempt records what it sent.
- `tests/contract/test_validators.py::test_sampling_sent_is_optional_and_never_empty`: a record without the key reads as `None`.
- `uv run pytest tests/contract tests/golden tests/llm -q` passes, and `fingerprints.json` and the goldens are unchanged.

## Consequences
- **Contract / fingerprint impact:** none on the renderer. `pl_user_v1`, `pl_cp_v1`, `pl_cp_v2` and `pl_cp_v3` are unchanged. `tests/contract/snapshots/event_registry.json` gains `sampling_sent` in the `llm.call` payload keys (additive). `manifest.schema.json` is unchanged. `CONTRACT_VERSION` stays `v1`.
- **Data invalidated:** none. Earlier bundles read with `sampling_sent = None`, which says only that the field was not recorded. For those bundles the sampling is unknown, not "provider default": they carry no claim that it had an effect.
- **Migration:** in-flight worktrees need nothing. The `llm.call` payload is validated by type, so older events still validate. Fakes and recorded replays may leave the field `None`. Root: `make pull-through MODE=verify` when it is available.
- **Risks and what would make us revisit this.** The table is static and covers one model. If another hosted model is adopted, re-fetch its `supported_parameters` and add a cited entry. If OpenRouter's list changes, update the entry and its date. A provider that silently ignores a parameter it does list cannot be detected here.
