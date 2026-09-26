# ADR-0004: Contract v1

- **Status:** accepted
- **Date:** 2026-09-26
- **Task:** S0-CON-01

## Context
S0-SYS-03…06 and S0-MOD-02 need one frozen contract under `src/proxyloop/contract/` (ARCHITECTURE §2, §4–§7, §12, §14). It must import only the standard library and pydantic. ADR-0001 and the user added constraints on the LLM types. The user raised this task's budget to about 1,700 changed lines (2026-09-26).

## Decision
Contract v1 (`CONTRACT_VERSION = "v1"`) is these modules, all pydantic models that are frozen and have `extra="forbid"`:
- `events` (`pl.event/2`, `EVENT_TYPES`) and `state` (the §5 blackboard plus the §9 authority types);
- `messages` (`FastToSlow` with `REVOKE`, `SlowToFast`, `Guide`, `GuideMove`, `SlotRef`) and `views`;
- `protocol` (the renderer, the budget, the grammar and `fingerprint`), with the `pl_user_v1` and `pl_cp_v1` profiles;
- `llm`, `config` and `bundle` (`pl.bundle/1`, `Manifest`, `read_bundle`).

Every S1 section is rendered from S0 on, with `(none)` when empty. `CONTEXT_BUDGET_CHARS = 12_000` covers the system and user text together. Over budget, the renderer drops the oldest transcript lines first, then the oldest actions; an overflow after that raises `ContextBudgetError`.

Decisions beyond the ARCHITECTURE text:
1. **`brief` is an argument** to `view_user`, `view_cp` and `view_slow`. The task's brief is task data, not blackboard state, so no state field was added.
2. **`ReadbackBinding` sits on `ApprovalCard`.** A validator requires its offer, revision and epoch to equal the card's.
3. **No Terms type in the contract.** `OfferPublic` carries read-back slots plus `terms_hash` (§9.2). Terms stay in `guard.terms` (SYS). D2 (whether `total_cost_12m_minor` is derived or stored) is **deferred to S1-SYS-01**.
4. **`ModelRef` fields.** They are `kind` (`AdapterKind`), `endpoint` (`relay | teamrouter | vllm`, or none for an in-process baseline), an exact `model_id` and `reasoning_effort`. A `real_http` model needs an endpoint; a baseline has none. The contract holds no URLs, keys or environment-variable names. `WorldModels` (ear, mouth, simuser) has no default, and each world model must set `reasoning_effort`. **This supersedes ADR-0001's `gpt-5.4-mini` world choice.** Per the user's decision of 2026-09-26, the world runs on `gemini-3.8-flash` through TeamRouter; that is a config value, not a contract constant.
5. **Exogenous events.** These types may have empty `cause_ids`:
   - ingress: `session.started`, `user.msg`, `utt.final`, `approval.post`;
   - types a timer can emit: `session.ended`, `parity.checked`, `attest.recorded`, `chan.strike`, `fast.request`, `slow.step.started`, `rep.policy`.

   `approval.post` is added to the registry, since §4.1 names it as ingress. Every cause must be an earlier event of the same run. Payloads must carry the §4.2 keys and may carry more.
6. **`LLMClient.stream_text`** yields text deltas, then exactly one `LLMCallRecord` as its last item.
   - A dead endpoint raises `LLMUnavailable`, which may carry the failed call's record.
   - `LLMCallRecord` stores `requested_model` (which must equal `model_ref.model_id`), `served_model_echo` and `usage.reasoning_tokens`.
   - `ToolRequest.tool_choice` names the one tool the model must call.
   - There is no `response_format` or JSON mode.
   - `request_content` and `tool_response_content` define what `prompt_sha` and `response_sha` hash.

Grammar (§6.2):
- The parser accepts TalkAct's tolerant rules (`fast_agent.py:168-191`):
  - inline `@slow:` is split out;
  - `FIRST:`/`THEN:` echoes are stripped;
  - only a line *starting* with `@end_call` ends the call.
- Wrong-lane directives, bad or duplicate holds, malformed typed facts, unknown `@` lines and empty turns become counted `ParseIssue` items.
- `format_turn` writes the canonical order.

## Evidence
- **Fingerprints** (`tests/contract/snapshots/fingerprints.json`):
  - `pl_user_v1` = `796d2843964be1f552b18836093915744a6c543d1fab148ad3ca10d50e5f9cfb`;
  - `pl_cp_v1` = `1efb67b22aa0814058b70c0f079a085701e2f674c3fbec104e25efc6b9252d0b`.
- **P2** (`tests/golden/p2_ids.json`):
  - the tokenizer is `Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a`, called with `enable_thinking=False`;
  - the empty think block is `"<think>\n\n</think>\n\n"`, hex `3c7468696e6b3e0a0a3c2f7468696e6b3e0a0a`, ids `[248068, 271, 248069, 271]`;
  - `apply_chat_template(tokenize=True)` equals `tokenize=False` plus `encode` on all 13 goldens;
  - the worst case is `c06_over_budget` at 3,605 tokens.
- **P1:** 13 goldens (6 user, 7 cp) in `tests/golden/views/`.
- **Contract tests** in `tests/contract/`:
  - P4 on 64 canonical turns, every split point, plus 300 arbitrary texts;
  - the private-value counterfactual over 500 blackboards;
  - the `view_cp` AST rule;
  - the registry and manifest snapshots.
- **Run:** `uv run pytest tests/contract tests/golden -q`.

## Consequences
- **Contract and fingerprints:** new (none → v1). The first `make pull-through` records the fingerprints above.
- **ARCHITECTURE diff:**
  - §2: the view signatures take `brief`;
  - §4.2: lists `approval.post{approval_id, decision, terms_hash, authority_epoch}`;
  - §16: the contract row goes 950 → 1,700 lines, so the S0 total becomes ≈ 4,250 and the S0–S1 total ≈ 6,400.
- **Data invalidated:** none.
- **Migration:** SYS and MOD import only from `proxyloop.contract`. `.importlinter` forbids the contract from importing the rest of `proxyloop`, the tests and the tokenizer libraries. Adapters run `tests/contract/llm_conformance.py`.
- **Risks:**
  - **S0 size tripwire.** The §16 S0 total (≈ 4,250) now exceeds PLAN §0.6's 3,700-line S0 tripwire. The tripwire was left unchanged, so the root must decide.
  - **`reasoning_effort` on TeamRouter.** The values accepted for `gemini-3.8-flash` are unprobed.
  - **P2 needs the Hugging Face tokenizer.** It comes from the network or the cache; the files are not vendored.
  - **Known P7 divergences from TalkAct (S4):**
    - unknown `@` lines are dropped as issues, where TalkAct speaks them;
    - speech is re-joined sentence by sentence with single spaces;
    - `@hold` after a `FIRST:` echo is spoken.
  - **`FastToSlow.text` is capped at 240 characters.** The kernel must decide how to handle a longer relay (count it, never repair it).
