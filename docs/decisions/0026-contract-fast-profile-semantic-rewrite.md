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
