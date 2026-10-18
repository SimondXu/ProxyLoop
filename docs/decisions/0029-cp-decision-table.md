# ADR-0029: The cp decision table (the next Fast cp profile)

- **Status:** accepted (the user, 2026-10-17, after the tuning rounds and the hold-out check below; S1-CON-12). Proposed 2026-10-12 (the session; the user lifted the freeze for this prep). `pl_cp_v5` lands as a candidate; the live flip and `make pull-through` come with the training data.
- **Date:** 2026-10-12
- **Task:** S1-MOD-12
- **Builds on:** ADR-0026 (hold semantics, relay scope). Supersedes its reservation of `pl_cp_v5` for ADR-0014's `defer_callback` (below).

## Context
On `pl_cp_v4` the remaining ambiguity is not where the instruments looked (principal-architect review, 2026-10-12, on `runs/profile-retest-0929` and `runs/label-review-pilot-1012`): with a hold standing and the representative speaking, DeepSeek medium keeps the hold in 14 of 18 set-A rows and Luna in 4 of 18; with a persisted `hold_*` guide on set B, DeepSeek drops a required hold in 15 of 45. `profile_check.hold_label` does not score either class. After a commit FastC still stalls and asks for read-backs (fc41ec, aebf80); part of that is the view (a voiced GUIDE re-triggered, `cp_hold` not cleared by a verbatim accept: PLAN Now/Next item 2), part is a status nobody explained. The pilot reviewer brief also contradicted the sticky hold. One specification is missing: the profile text, `profile_check` and the reviewer brief each say it their own way.

## Decision
The cp lane's behaviour is this table. Every rule is decided from rendered fields only: TRIGGER kind, HOLD STATUS, CASE STATUS, the newest CASE AGENT GUIDANCE move, and the representative's lines since the agent last spoke. The profile text states it, `profile_check` scores it, the reviewer brief quotes it and adds nothing. A case the table does not decide is `ambiguous:<rule>` (the reviewer drops the row; the class goes back into the table).

| # | When (first match wins within a group) | Then |
|---|---|---|
| **Status (overrides the hold rules)** | | |
| S1 | CASE STATUS is COMMITTED, EVIDENCE_PENDING or VERIFIED_COMPLETE | The deal is done and was said for you. No `@hold`; do not ask for a read-back; do not say you cannot accept. Thank them; relay any confirmation number or term they state (R1); `@end_call` only by C1. |
| S2 | CASE STATUS is AWAITING_APPROVAL or COMMIT_AUTHORIZED | Your customer is deciding or has decided; any acceptance is said for you word for word, never by you. The hold rules apply. |
| S0 | Any status | Never accept, agree to or commit to anything yourself (I6). |
| **Hold** | | |
| H1 | TRIGGER is new guidance and the newest move is `hold_for_decision` or `hold_for_fact` | Stall; end with `@hold decision` / `@hold fact_request`. |
| H2 | No hold standing; the representative just asked you to accept, agree to or choose something, or acts as if you had | Stall; `@hold offer` (an offer) or `@hold decision`; `@hold pressure` if they demand an answer now. |
| H3 | No hold standing; the representative asked for a detail you were not given | Stall; `@hold fact_request`. With new guidance `deflect_fact_request`: say you cannot share it, no hold. |
| H4 | A hold stands (HOLD STATUS) and TRIGGER is `rep_spoke` or `hold_wait` | Answer briefly and end with the same `@hold <reason>`; relay what they said (R1). |
| H5 | A hold stands and TRIGGER is new guidance that is not a hold move | Do the guidance without `@hold`; that ends the hold. |
| H6 | Anything else | No `@hold`. |
| H7 | Always | Stalling speech ("I need to check with my customer, please hold") ⇔ a `@hold` line, both directions. |
| **Relay** | | |
| R1 | TRIGGER is `rep_spoke` | Relay what the representative said since you last spoke: one `@slow: fact <key>=<value>` per price, fee, term, date or change, including terms they restate; anything else the case agent should know as one `@slow: <sentence>`. |
| R2 | Any other trigger | No `@slow:` line. |
| **Guidance, silence, call** | | |
| G1 | TRIGGER is new guidance (and S1, H1, H5 do not decide) | Do the newest move. |
| G2 | TRIGGER is `rep_spoke` and the newest move is not new | Respond to the representative; do the move again only if the conversation shows it is not done. (Judgment; the reviewer may mark `ambiguous:G2`.) |
| W1 | The representative asks you to wait or says they are checking | `@wait` and nothing else. No other turn has `@wait`. |
| C1 | The newest move is `close_call` | Thank them, say goodbye, end with `@end_call`. No other turn has `@end_call`. |

- **Wording** follows the principal-architect's draft (hold, relay, status paragraphs; about +100 Qwen tokens over `pl_cp_v4` [E]); the example keys become keys no family uses. The user lane freezes `pl_user_v2` in the same change.
- **Name.** The next cp profile is `pl_cp_v5`. ADR-0014's `defer_callback` is descoped from it: adding that move later is a new profile version and invalidates SFT data built on this one (PLAN, Frozen; ADR-0014 stays deferred).
- **Kernel, not text.** The stale guidance trigger and the sticky `cp_hold` after a verbatim accept are fixed in the kernel (PLAN Now/Next item 2), not by wording.

## Validation (before the CON task)
Tuning on set A plus post-M1 states (runs 4b9901, afa368, 99c310, aebf80) and new set-C-style asks; hold-out = set B, the pinned set C and fc41ec, read as aggregates only. Round 0 measures the noise floor (v4: DeepSeek medium twice, Luna once). One rule per round; Luna none co-gates every round (AGENTS rule 12); GLM none as a control at the final check. Pass, on the hold-out for DeepSeek medium and Luna none: D6 = 0 and T3 = 0 on set C's asks; required holds (H1–H4) ≥ 95 % with the table's reason; forbidden holds ≤ 5 %; malformed ≤ 1/127; non-partner relays ≤ 5 %; H7 incoherence 0 in final labels; S1 violations 0; D7 p90 ≤ 160 and cp speech ≤ 40 words, no worse than v4; D5 relay recall not below v4; example parroting 0. A class that has not moved beyond the noise floor after 3 rounds is a view or capability problem: write the rethink. At most 5 rounds.

## Consequences
- **Contract:** none yet; the profile text lands with its own CON task after validation, then `make pull-through MODE=full`. The live profile stays `pl_cp_v3` through M2.
- **Instruments:** `profile_check` gains H4, H5, H7, S1 and R2 counts; the reviewer brief is rewritten to quote this table.
- **Data:** no SFT label is built before this profile is final.

## Result (2026-10-15..17, S1-CON-12)
`pl_cp_v5` (system sha256 `56de846c3973894aaed17fdf91ad5805ce10606012b8268afa8be445f8d8920c`, fingerprint `e6fcdfe95dadceea9388daf28f56564a519038907d7ec9ffefd64e2a50c2718e`) is `pl_cp_v4` with a new system text. Moves and grammar are v4's. The text adds:
- what CASE STATUS means (S1, S2);
- H4: answer briefly, say you are still checking, keep the same `@hold` even on a thank-you; under a hold, guidance that is not new is not done again;
- H5 and H7;
- `@wait` only when asked to wait (W1);
- no `@slow` unless the trigger is `rep_spoke`, and never relay your own words (R2);
- each sentence once, no directive names in speech.

Sets: `cp_sets --seed 12` (tune 346 views + 20 constructed S1; hold-out 80 + 8) plus S1-MOD-10's set B and the pinned set C. `probe_same_state`, `--max-tokens 16384`. Scored by `cp_table` and by `profile_check check --allow-other-plan` (the tune or hold-out set as A). The PR body of S1-CON-12 has the per-round table. Bundles are local (`runs/cp-round0-1015`, `runs/cp-round1-1015`, `runs/cp-holdout-1017`).

| DeepSeek medium | v4 (two runs) | v5 |
|---|---|---|
| tune S1 (post-commit) | 20/20, 20/20 | 20/20 |
| tune H4 | 44/67, 40/67 | 56/67 |
| tune H5 | 15/20, 14/20 | 20/20 |
| tune H7 incoherent | 0, 0 | 0 |
| tune non-partner relays | 23/112, 12/112 | 3/112 |
| tune D5 relay recall | 53/78, 56/78 | 58/78 |
| tune Qwen-token p90 | 88, 87 | 78 |
| hold-out S1 (real / constructed) | — | 4/4, 8/8 |
| set B named reason | 36/52 | 40/52 |
| set C fit reason | 24/30 | 24/30 |

Luna none (one run each), v4 → v5: tune S1 17 → 20/20; H4 26 → 40/67; D5 24 → 36/78; set C fit reason 19 → 14/30. Luna has no noise run.

**Deviations from the bars (accepted by the user, 2026-10-17):**
- **H4 is 56/67 (84 %), below the 95 % bar.** A row audit of the 11 misses on the tune set:
  - 1 real miss: stalling words without `@hold`.
  - 1 minor miss: the shown move redone under a hold.
  - 3 debatable: the representative named a new offer during the hold, and FastC asked for its read-back.
  - 6 are not FastC errors:
    - 4 come from a stale HOLD STATUS: the verbatim decline was said, or the fact was answered, but `cp_hold` still stands (it changes only through a Fast turn's `chan.hold`);
    - 1 changes the reason from `fact_request` to `decision` once the read-back is done;
    - 1 is `close_call`.

  Without the 6, H4 is 62/67 (93 %). The stale hold is a kernel and hold-semantics question, handled as its own task.
- **Example parroting is 5 on set C (bar 0).** DeepSeek reused the format example's "I can't agree to that myself." when asked to accept. It is the correct refusal, in the situation the example shows. On the tune set the count is 0. The examples stay; `profile_check` pins the example list.
- **GLM none was not run.** TeamRouter now refuses reasoning off for `glm-5.3-flash` (HTTP 400, "always thinks").
- **T3 on set C was not judged** (no blind labels in this check).
