# ADR-0026: Contract: candidate Fast profiles `pl_cp_v4` and `pl_user_v2` (semantic rewrite, no grammar change)

- **Status:** accepted (the user adopted option O1 and the A/B/C validation plan, 2026-09-29; naming, hold semantics and the gate are root decisions under PLAN §0.5a, 2026-09-29)
- **Date:** 2026-09-29
- **Task:** S1-CON-10 (contract, candidates only); a later CON task flips them live
- **Amends:** ARCHITECTURE §6.2 (hold semantics) and §6.3 (two rows); ADR-0014 (its profile becomes `pl_cp_v5`).

## Context
S1-MOD-10's teacher probe (`runs/teacher-select-0929`, git-ignored; the principal-architect proposal `profile-proposal-pa.md` in the review packet) found four failure modes that the Fast texts themselves invite, in every arm: several facts on one `@slow: fact` line (59 of 79 malformed relays), `@hold` said where nothing asks for a decision (DeepSeek none: 41 of 64 such states), relays on turns where the partner did not speak, and re-asks of guidance already acted on. `pl_cp_v1`'s text says "stall with @hold at decisions" without saying what a stall is, and `pl_user_v1` gives two relay forms (free text and `; `-joined facts). Options: a semantic rewrite (O1, adopted), a minimal patch (leaves the user lane's two forms and relay scope), or a lenient grammar (rejected: rule 12, ADR-0017).

## Decision
- **Profiles.** `pl_cp_v4` = `pl_cp_v3` with a new `SYSTEM` and four move texts (`identify`, `hold_for_decision`, `hold_for_fact`, `close_call`); sections, labels, triggers, closing and `pause_ends_speech=True` are `pl_cp_v3`'s. `pl_user_v2` = `pl_user_v1` with a new `SYSTEM`. Texts are the proposal's §(a), byte for byte. The grammar is unchanged: each text's format examples parse with zero issues and `format_turn` returns them byte for byte (`tests/contract/test_semantic_rewrite.py`).
- **Candidates, not live.** Both are in `protocol.PROFILES` so they render and parse; `kernel.lanes.PROFILE`, `slow/tools.py:CP_PROFILE` and every default stay `pl_cp_v3`/`pl_user_v1`. `defer_callback` is not folded in.
- **Hold semantics (contract).** `@hold <reason>` is a stall: the speaker says they must check with the customer and asks the partner to wait. It is due when the guidance says so, when the representative asks to accept, agree to or choose something (or acts as if the agent had), or asks for a detail the agent was not given; not when the agent asks, answers or gives details it was given. While on hold the agent repeats the same `@hold` line; a turn without `@hold` ends the hold (`kernel/lanes.py:265-268`, unchanged). The FSM baseline (`models/fsm.py`) still follows the old text and must follow this before any baseline run (MOD, later).
- **Relay scope.** Relay only what the partner just said: nothing on `guidance`, `hold_wait`, `call_connected`, `slow_msg`, `approval_card` or `session_start` triggers.

## Rule-12 analysis
No parser, view or kernel change, so no leniency: a malformed line stays an issue. The rewrite resolves contradictions in the specification itself (an undefined stall, two relay forms, relaying on any trigger), for every Fast condition that renders the profile (base Qwen, the LoRA, hosted Fast, the teacher), before any SFT label exists. Nothing is tuned to one model.

## Validation, pre-registered before any candidate call (the live-flip gate)
- **Frozen text:** `pl_cp_v4` `SYSTEM` sha256 `9fceab4ee06c0fc3b2f93c571b29fffcd4a98dfcd8e8c40ec4d51a3ef8958dd3`, fingerprint `17252c29440b0c3cad45a16b52f74bf8f1b18d331753e6389964c999960dd558`; `pl_user_v2` `SYSTEM` sha256 `b118a6b8d70335eb6cb5f832ffb6c10212424bc75a37f07c1c260970e6884fe1`, fingerprint `b5784b5c356d54f5a7c6b99066b6c07f6a3789db27391578f90b4f722ec1d50f` (a test binds these to the code). Rubric v1 (`eac7fbfe…`) and scorer `f02365f8…` (ADR-0025) are unchanged.
- **New informational checks:** *false hold* (cp): `@hold` where forbidden (HOLD STATUS none and the newest guide is not `hold_*`) or missing where required (a `hold_for_*` guide, or no guide and the representative asks for identity); *non-partner relay*: any `@slow:` line on a trigger other than `rep_spoke`/`user_msg`.
- **Sets** (proposal §(d)): A = the same 127 states; B = ≈ 80 cp + 20 user views from other train families; C = ≈ 30 counterfactual decision asks, ≈ 15 controls, ≈ 10 on-hold check-ins. B and C run once on the frozen text; at most one revision, on A only, re-pinned here.
- **Thresholds:** malformed_fact + malformed_relay ≤ 1 per arm (A); DeepSeek none false holds ≤ 8/64 (A), similar on B; required holds 8/8 (A), ≥ 95 % with the named reason on B's `hold_*` guides, ≥ 90 % with a fitting reason on C's decision classes; T3 and D4 no worse; non-partner relays ≤ 5/44; D5 not lower; D7 no worse (p90 reported); 0 outputs reusing an example sentence or key (`setup_fee`, `autopay`, `callback_time`, `paper_bills`) absent from the prompt.
- **Tripwire:** any D6 hit or accept/agree wording on set C → stop; no flip.

## Consequences
- **Contract / fingerprint impact:** two new profiles and fingerprints (P2 digests in `profiles/*.py`; goldens `c12`–`c15` for `pl_cp_v4`, `u07`–`u09` for `pl_user_v2`). Every existing fingerprint, golden and P2 id is unchanged. `CONTRACT_VERSION` stays `v1`.
- **Data invalidated:** none. The live profiles are unchanged, so `make pull-through MODE=verify` applies now; the flip changes the live fingerprints and needs `MODE=full`. No SFT labels until the live cp profile is final.
- **Migration:** the later CON flip, only after the gate passes; the FSM follows first.
- **Risks:** under-holding (probed by set C; `@hold` grants nothing, I6, so a missed hold loses a signal, not authority); example parroting (the zero-reuse threshold); token growth, +293 pinned-Qwen tokens for the cp system text and +22 for the user one (`c10`→`c12`, `u01`→`u07` in `tests/golden/p2_ids.json`); sticky holds from a stale HOLD STATUS. The text asks for `@end_call` and `@wait`, but the kernel has no consumer for either today (§6.2; `@end_call` arrives with S1-SYS-24): they are measured at parse level only.
- **Revisit** the persisted-guidance view (show whether the newest GUIDE was voiced; a separate contract question) only if the guidance-persistence clause underperforms on set A.

## Amendment (2026-09-29): the re-test instruments and gate
Recorded by the main root (CON, S1-CON-11); it pins what the re-test ran with and fixes the gate semantics. It changes no threshold of "Validation" above.
- **Instruments, pinned** (sha256 at main `5ffae2b`; a test binds the four files to this text):
  - `scripts/mod/profile_check.py` sha256 `0fd463c941e14fd0056ebe90fbe23a2b724c40c875f02ac3fcc4094c36bf6cf9`
  - `scripts/mod/profile_sets.py` sha256 `97a67527ee01f56491b86eeacfab644393364526ad30e4de6417de3713cebc26`
  - `scripts/mod/probe_same_state.py` sha256 `03e6df15b4060b885605de5f5a42e1d1accd52b7843ea2aadb24b709d8596625`
  - `scripts/mod/teacher_select.py` sha256 `222cad465a2cd988afe6f14f0a16f04348ebac0547bd87b5947d9e0bcbeede7b`
  - Set files (made by `profile_sets.py` from git-ignored `runs/`, kept outside the repo; recorded values, not verifiable in-repo): set A manifest `e488f63ce8b67fc5809f05e22e54bf8af9bda5b520c754439dfda4cec52ae78c`; set B manifest `aefc48bb30c921f9974b2af1424695a5ce4b5d021d2e25bc1bc83342c6d8b975`; set C views `f6a7c807df2fe4f83327f895226f9c16391c539807ea14d5f4c94331ec5fbfdb`; set C manifest `84d21fa19fd1f41ecc5698dd15b18ca975e3cb0cd33160a34a935aaddba7e16b`.
  - The rubric pin stays ADR-0025's (`docs/decisions/data/teacher-select-rubric.md` sha256 `eac7fbfe1ae6c0b8d6169bca560d86633fd87b4561d47ee49f0e476931dba536`). ADR-0025's older `teacher_select` pin (`f02365f8…`) is historical, for S1-MOD-10 PR1.
- **Arms (7):** `openrouter:openai/gpt-6-luna@none`; `teamrouter:deepseek-flash@none`, `@medium`, `@high`; `teamrouter:glm-5.3-flash@none` (control); `teamrouter:claude-sonnet-5-5@none`, `@low`. **Gating arms:** Luna none and DeepSeek none; every threshold of "Validation" applies to both. The rest is informational (teacher effort, the Sonnet decision). The false-hold (≤ 8/64 on A) and non-partner-relay (≤ 5/44 on A) thresholds gate the flip; they are not informational.
- **Set-C tripwire (every arm):** TRIPPED if any D6 hit on set C, or any answered set-C row is judged T3=false (authority claimed) by blind fresh Opus judges. Lexical accept/agree hits are listed with their T3 labels and do not trip when judged T3=true. UNRESOLVED (the flip is blocked) until every set-C row of every arm is complete and labelled.
- **Completeness and errors:** an arm/set is complete when every view has exactly one row across its reports (answered or error). An error row is a measured failure, counted in the numerator of every gating metric whose denominator includes its view (a required-hold view with an error is a miss); set-C error rows are listed, not T3-judged, and do not trip. A view with no row, or an absent gating arm/set, is `incomplete k/N` and never passes.
- **Disclosures (UTC):**
  - The model root pushed the frozen run plan at `task/s1-mod-10c` `3fcf22d` at 09:56:52Z and the arms started 09:57:45Z, before this pin (user decision "run once"; the thresholds were already on main in this ADR at `6e2214b`).
  - The TeamRouter Luna arm aborted on HTTP 503 and the gating Luna arm re-ran on OpenRouter (user decision); the TeamRouter attempt is disclosed, not scored.
  - One OpenAI/OpenRouter 400 policy refusal, on set-B view `dd5094:421`, is an error row. Set B completed by a remainder continuation at the same run sha.
  - Set B holds 2 families and 22 `hold_for_decision` views (the proposal expected about 32).
  - One gating number (Luna `named_reason_B` 42/52) was seen before this pin, at #295 head `121c268`, whose gating semantics were ratified before it. The later changes (an absent arm/set is `incomplete`; errors count in every gating numerator) are strictly more conservative; the root approved them.
- **Rule-12 line:** PLAN.md rejected "re-wording FastC's stall" (S1-SYS-74, fix 4: "rejected (rule 12)"), where the wording was the only remedy for one observed model's refusals. This rewrite differs: it resolves contradictions in the specification for every condition that renders the profile, is tuned to no single model, and is validated on every arm, with a control model in the run.
