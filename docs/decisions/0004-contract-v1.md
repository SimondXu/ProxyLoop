# ADR-0004: Contract v1

- **Status:** accepted
- **Date:** 2026-09-26
- **Task:** S0-CON-01

## Context
S0-SYS-03…06 and S0-MOD-02 need one frozen contract under `src/proxyloop/contract/` (ARCHITECTURE §2, §4–§7, §12, §14). It must import only the standard library and pydantic. ADR-0001 and the user added constraints on the LLM types. The user raised this task's budget to about 1,700 changed lines, then src to 1,850 and 1,900 for the review rounds (2026-09-26).

## Decision
Contract v1 (`CONTRACT_VERSION = "v1"`) is these modules, all pydantic models that are frozen and have `extra="forbid"`:
- `events` (`pl.event/2`, `EVENT_TYPES`) and `state` (the §5 blackboard plus the §9 authority types);
- `messages` (`FastToSlow` with `REVOKE`, `SlowToFast`, `Guide`, `GuideMove`, `SlotRef`) and `views`;
- `protocol` (the renderer, the budget, the grammar and `fingerprint`), with the `pl_user_v1` and `pl_cp_v1` profiles;
- `llm`, `config` and `bundle` (`pl.bundle/1`, `Manifest`, `read_bundle`).

Every S1 section is rendered from S0 on, with `(none)` when empty. `CONTEXT_BUDGET_CHARS = 12_000` covers the system and user text together. Over budget, the renderer drops the oldest transcript lines first, then the oldest actions; an overflow after that raises `ContextBudgetError`.

**Render bounds** (`base.MAX_*`): brief 800, private summary 1,200, public summary and Slow's user text 400, read-back text 600, public fact value 120, slot value 24 and field 40, 6 offers of at most 10 slots, 3 guide slots of at most 80 characters, offer refs of at most 24. A view with every bounded field at its maximum fits the budget, and the transcript and action log absorb the rest (`tests/contract/test_budget.py`). So `ContextBudgetError` is unreachable for validated views.

Decisions beyond the ARCHITECTURE text:
1. **`brief` is an argument** to `view_user`, `view_cp` and `view_slow`. The task's brief is task data, not blackboard state, so no state field was added.
2. **`ReadbackBinding` sits on `ApprovalCard`.** A validator requires its offer, revision and epoch to equal the card's.
3. **No Terms type in the contract.** `OfferPublic` carries read-back slots plus `terms_hash` (§9.2). Terms stay in `guard.terms` (SYS). D2 (whether `total_cost_12m_minor` is derived or stored) is **deferred to S1-SYS-01**.
4. **`ModelRef` fields.** They are `kind` (`AdapterKind`), `endpoint` (`relay | teamrouter | vllm`, or none for an in-process baseline), an exact `model_id` and `reasoning_effort`. A `real_http` model needs an endpoint; a baseline has none. The contract holds no URLs, keys or environment-variable names. `WorldModels` (ear, mouth, simuser) has no default, and each world model must set `reasoning_effort`. **This supersedes ADR-0001's `gpt-5.4-mini` world choice.** Per the user's decision of 2026-09-26, the world runs on `gemini-3.8-flash` through TeamRouter; that is a config value, not a contract constant.
5. **Exogenous events.** These types may have empty `cause_ids`:
   - ingress: `session.started`, `user.msg`, `utt.final`, `approval.post`;
   - types a timer can emit: `session.ended`, `parity.checked`, `attest.recorded`, `chan.strike`, `fast.request`, `slow.step.started`, `rep.policy`.

   `approval.post` is added to the registry, since §4.1 names it as ingress. Every cause must be an earlier event of the same run.

   **Typed payloads.** `llm.call` (`LLMCallRecord`), `f2s.msg`, `s2f.msg`, `approval.requested` (`ApprovalCard`), `approval.post`, `approval.decided`, `mandate.proposed` (`Mandate`), `mandate.decided{mandate_id, mandate_hash, decision, by}`, `authority.epoch{new, reason: mandate_decided|slow_revoke|tighten_mandate|f2s_revoke}`, `action.authorized{intent, capability}`, `status.changed{previous, status}` and `completion.decided` are validated through closed models. Other payloads must carry their §4.2 keys and may carry more. A granted or denied `Mandate` must name `decided_by`.
6. **`LLMClient.stream_text`** yields text deltas, then exactly one `LLMCallRecord` as its last item.
   - A dead endpoint raises `LLMUnavailable`, which always carries the failed call's record.
   - `LLMCallRecord` stores `requested_model` (which must equal `model_ref.model_id`), `served_model_echo`, `usage.reasoning_tokens`, `finish_reason` and `attempt` (0 or 1). There is one record per HTTP attempt, so a retry is two records.
   - For `real_http`, the conformance kit requires a non-empty `request_id` and `completion_tokens > 0` (ARCHITECTURE §14).
   - `ToolRequest.tool_choice` names the one tool the model must call.
   - There is no `response_format` or JSON mode.
   - `request_content` and `tool_response_content` define what `prompt_sha` and `response_sha` hash.
   - Model or world text over a contract bound (for example `FastToSlow.text` over 240 characters) is rejected and counted at the write boundary, never truncated.
7. **Actors (review M3, root decisions).** `Event.actor` is one of `fast.user`, `fast.cp`, `slow`, `guard`, `kernel`, `ui`, `sim_approver`, `world.ear`, `world.policy`, `world.mouth`, `world.simuser`, `world.ledger` (`events.ACTORS`). The allowed emitters (`events.EMITTERS`) cover the §4.2 authority group and the state types that feed it:

   | Event | Allowed actors |
   |---|---|
   | `approval.post` | `ui`, `sim_approver` |
   | `approval.decided`, `mandate.decided` | `kernel` |
   | `authority.fence`, `authority.epoch` | `kernel`, `guard` |
   | `mandate.proposed`, `approval.requested`, `action.authorized`, `speak.verbatim`, `speak.released`, `screen.redacted`, `evidence.recorded`, `offer.recorded`, `readback.updated`, `completion.decided`, `status.changed` | `guard` |

   - Slow's tool effects reach the log as `guard` events.
   - The restrict-only types (`action.denied`, `speak.revoked`, `declass.denied`) and `fact.recorded` (information) accept any actor: models may restrict authority, never grant it.
   - No `fast.*`, `slow` or `world.*` actor may emit a restricted type.

   `events.check_causes` checks the log; `read_bundle` runs it:
   - every cause is an earlier event of the log;
   - each `approval.decided`/`mandate.decided` cites exactly one `approval.post`, matching its subject, subject id, decision and `by` (which must equal the post's actor), and, for a mandate, `subject_hash == mandate_hash`;
   - each post is decided at most once.

   Mandate decisions arrive through the same endpoint, so `approval.post` is `{subject: approval|mandate, subject_id, decision, subject_hash, authority_epoch}`, where `subject_hash` is the card's `terms_hash` or the `mandate_hash`. `mandate.proposed` requires `status == "proposed"` and no `decided_by`.
8. **`SessionConfig`.** It has `teacher: ModelRef | None`, set iff a `teacher_repair_*` ablation is (part of `cfg_hash`). With `live=True`, no role may be `test_fake` or `recorded_replay`, and `baseline` (the FSM) is allowed only on `fast_user`/`fast_cp`.

Grammar (§6.2):
- The parser keeps exactly TalkAct's tolerances (`fast_agent.py:168-191`) and no others:
  - inline, case-insensitive `@slow:` is split out;
  - `FIRST:`/`THEN:` echoes are stripped;
  - a trailing `@end_call` is stripped;
  - only a line *starting* with `@end_call` (case-insensitive) ends the call.

  Everything else is case-sensitive.
- Every deviation becomes a counted `ParseIssue`:
  - `wrong_lane`, `unknown_directive`, `bad_hold_reason`, `duplicate_pause`, `duplicate_end_call`, `empty_turn`;
  - `malformed_fact`, and `malformed_relay` (an empty `@slow:`, a wrong-case or textless typed head, or an unknown head followed by `key=value` pairs); these stay a NOTE, as in TalkAct;
  - `stray_directive`: a line or sentence that starts with `@` after scaffold stripping is never spoken;
  - `inline_directive`: a mid-sentence `@hold`/`@wait`/`@end_call` stays spoken, as in TalkAct; a trailing `@end_call` is stripped and not honoured;
  - `scaffold_echo`: a sentence that still starts with `FIRST:`/`THEN:` or ends in a scaffold.
- `format_turn` keeps item order and refuses a Speech that is not a canonical sentence (for example one starting with `@`). For any text x, `parse(format(strip_issues(parse(x)))) == strip_issues(parse(x))`, and streaming parse equals batch parse.

## Evidence
- **Fingerprints** (`tests/contract/snapshots/fingerprints.json`):
  - `pl_user_v1` = `796d2843964be1f552b18836093915744a6c543d1fab148ad3ca10d50e5f9cfb`;
  - `pl_cp_v1` = `76a0185865410a3e30755be079c5b539180171114ce82e0a6c8c4a0bb668b490`.

  The renderer bytes did not change in the review round. The `pl_cp_v1` golden `c07` changed (its long brief exceeds the new bound; long actions force the trimming instead), so the cp P2 ids and fingerprint changed.
- **P2** (`tests/golden/p2_ids.json`):
  - the tokenizer is `Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a`, called with `enable_thinking=False`;
  - the empty think block is `"<think>\n\n</think>\n\n"`, hex `3c7468696e6b3e0a0a3c2f7468696e6b3e0a0a`, ids `[248068, 271, 248069, 271]`;
  - `apply_chat_template(tokenize=True)` equals `tokenize=False` plus `encode` on all 13 goldens;
  - the worst-case token count is recorded under `worst_case` in `tests/golden/p2_ids.json` and asserted by `tests/golden/test_p2.py::test_worst_case_is_recorded`.
- **P1:** 13 goldens (6 user, 7 cp) in `tests/golden/views/`.
- **Contract tests** in `tests/contract/`:
  - P4 on 64 canonical turns at every split point, plus 500 arbitrary texts for streaming equals batch and for the parse/format fixpoint;
  - the counterfactual over 500 blackboards, perturbing every Blackboard field except `public` and `channels["cp"]`, with a non-vacuity check on `view_user`;
  - the `view_cp` AST rule (only `bb.public` and `bb.channels` with the literal key `"cp"`);
  - the render-bounds test;
  - the registry, actor-table and manifest snapshots.
- **Run:** `uv run pytest tests/contract tests/golden -q`.

## Consequences
- **Contract and fingerprints:** new (none → v1). The first `make pull-through` records the fingerprints above.
- **ARCHITECTURE diff:**
  - §2: the view signatures take `brief`;
  - §2: the `contract.config` row states the `teacher` and live-mode rules;
  - §4.1: the actor vocabulary, the fixed emitters and the decision-citation rule;
  - §4.2: lists `approval.post{subject, subject_id, decision, subject_hash, authority_epoch}`, the payloads of `authority.epoch` (with its reasons), `mandate.proposed`, `mandate.decided` and `status.changed`, the `llm.call` fields `requested_model`, `finish_reason` and `attempt`, and that these payloads are typed;
  - §16: the contract row goes 950 → 1,900 lines, so the S0 total becomes ≈ 4,450 and the S0–S1 total ≈ 6,600.
- **Data invalidated:** none.
- **Migration:** SYS and MOD import only from `proxyloop.contract`. `.importlinter` forbids the contract from importing the rest of `proxyloop`, the tests and the tokenizer libraries. Adapters run `tests/contract/llm_conformance.py`.
- **Risks:**
  - **S0 size tripwire.** The §16 S0 total (≈ 4,450) now exceeds PLAN §0.6's 3,700-line S0 tripwire. The tripwire was left unchanged, so the root must decide.
  - **`reasoning_effort` on TeamRouter.** The values accepted for `gemini-3.8-flash` are unprobed.
  - **P2 needs the Hugging Face tokenizer.** It comes from the network or the cache; the files are not vendored.
  - **Known P7 divergences from TalkAct (S4):**
    - lines or sentences starting with `@`, and sentences that still carry a scaffold, are dropped as issues, where TalkAct speaks them;
    - speech is re-joined sentence by sentence with single spaces.
  - **`FastToSlow.text` is capped at 240 characters.** The kernel must decide how to handle a longer relay (count it, never repair it).
