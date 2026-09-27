# ADR-0011: Contract: the `openrouter` endpoint and the `hold_for_fact` GUIDE move (profile `pl_cp_v2`)

- **Status:** accepted (user decision 2026-09-27: "换 OpenRouter 的 Luna，加 hold_for_fact"; the v2 profile and the frozen v1: root decision)
- **Date:** 2026-09-27
- **Task:** S1-CON-04

## Context
- **Identity stalls.** With Luna as FastC, every gate smoke ended `abandoned` in IDENTIFY (the main root's live runs `runs/20260927T032340Z-cb8cb2` and `runs/20260927T032440Z-365e7b`, in the main checkout's git-ignored `runs/`). When the rep asks for identity facts the agent does not have yet, Slow can only guide `hold_for_decision` ("Say you need to check with your customer (@hold decision)"). FastC voices that as "…before making any decision", and the Ear hears it as `ask_discount`. Without that guide, FastC says "I can't provide those" (`refuse_fact`). No move says "hold on, I'm getting that detail from my customer", although the grammar already has `@hold fact_request`.
- **Endpoint.** The user moved hosted Fast development to OpenRouter (`openai/gpt-6-luna`). `contract.llm.Endpoint` has no `openrouter`, so a `ModelRef` for it cannot be built.
- **Options for the move.** Edit `pl_cp_v1`'s move map (rejected: it changes `pl_cp_v1`'s fingerprint, and the committed `evidence/s0` bundles, which record that fingerprint, would stop verifying); overload `deflect_fact_request` or `hold_for_decision` (rejected: a different act, and the Ear would still mislabel it); a new move rendered by a new profile (chosen).

## Decision
- `Endpoint = Literal["relay", "teamrouter", "vllm", "openrouter"]`. The contract names it only; SYS resolves its URL and key.
- `GuideMove.HOLD_FOR_FACT = "hold_for_fact"`, appended last so the existing members keep their order.
- New profile `pl_cp_v2` (`contract/profiles/pl_cp_v2.py`) is `pl_cp_v1` with one more move text: "Say you are getting that detail from your customer and ask them to hold a moment (@hold fact_request)." The system text, sections, labels, triggers and closing are identical. It is registered in `protocol.PROFILES`.
- **`pl_cp_v1` is frozen byte for byte**, and it has no text for `hold_for_fact`. Rendering that move with `pl_cp_v1` raises `protocol.GuideMoveError` (a `ValueError`, deliberately not a `GuideSlotError`), so it never renders silently.
- Goldens: two new `pl_cp_v2` cases (`c08_v2_empty`, `c09_v2_hold_for_fact`) bind `pl_cp_v2.p2_ids_sha256`; the v1 goldens and digests are unchanged. The private-value counterfactual property now renders with `pl_cp_v2`, which covers every move.

## Evidence
- `proxyloop.contract.protocol.fingerprint` on the branch: `pl_user_v1` = `796d2843…9cfb` and `pl_cp_v1` = `76a01858…b490`, both as recorded in `PLAN.md` and `tests/contract/snapshots/fingerprints.json`; `pl_cp_v2` = `ccc12390…0ab2` (new).
- `uv run pytest tests/contract tests/golden -q` passes; the four `evidence/s0` bundles still pass `make evidence-check`.

## Consequences
- **Contract / fingerprint impact:** `pl_cp_v2` is new; `pl_user_v1` and `pl_cp_v1` are unchanged. The manifest JSON schema snapshot gains `openrouter` in its endpoint enum. `CONTRACT_VERSION` stays `v1` (additive).
- **Data invalidated:** none. No training data has been rendered yet (S0-MOD-03 has not run).
- **Migration (follow-ups, outside the contract):**
  - L-CORE: `kernel/lanes.py` `PROFILE["cp"]` and `slow/tools.py` `public_guide` switch to `pl_cp_v2`. Until then Slow's `act` schema already offers `hold_for_fact` (`slow/prompt.py` enumerates `GuideMove`), and a Slow that picks it fails the session loudly (`GuideMoveError`). The `act` tool schema snapshot changes with it.
  - SYS: `llm/relay.py` `ChatClient.ENDPOINTS` gains `openrouter` (`llm/factory.py` already routes every non-`vllm` endpoint to it, and `llm/http.py` `EndpointEnv` reads `PL_OPENROUTER_BASE_URL` / `PL_OPENROUTER_API_KEY` generically); `cli.py` offers it through `get_args(Endpoint)`.
  - MOD: the baseline FSM (`models/fsm.py`) needs a `hold_for_fact` line and `Hold("fact_request")`, and must not pick a profile by system text alone (`pl_cp_v1` and `pl_cp_v2` share it); `tests/models/test_repair.py` names the new goldens.
  - Root: `make pull-through MODE=verify` when #125 provides it.
- **Risks and what would make us revisit this.** Two profiles share one system text, so any consumer that identifies a profile by its system message must take the lane only, or read the profile name from the event. Revisit if the Ear still mislabels the fact hold after the switch.
