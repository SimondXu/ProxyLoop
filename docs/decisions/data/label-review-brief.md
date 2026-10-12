# Label review brief v1 (ADR-0022 amendment 2, ADR-0029)

You review one training label at a time for a small "Fast" voice model. Each item has `system` and `user` (the exact prompt the model received), `lane` (`cp`: a live phone call with a company representative; `user`: an app chat with the customer) and `output` (what a teacher model wrote). The `system` text is the format specification.

## The rules (cp lane): ADR-0029's decision table, verbatim

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

User lane: relay task-relevant facts, corrections and requests from the user with `@slow:` (a stop or a change of mind is `@slow: revoke` at once); explain an approval card with its numbers and ask the user to review it; never say the task is done unless CASE STATUS is VERIFIED_COMPLETE; `@wait` only when sending no message.

Both lanes: say only facts in the prompt; no invented price, fee, date or personal detail; speech first, directives after, in the system text's format; one or two short sentences, natural speech, no markdown or meta-text.

## Your verdict

- `keep`: the output follows every rule that applies.
- `edit`: only directive lines are wrong. Give operations; the speech stays as written:
  - `{"op": "add_hold", "reason": "<offer|decision|fact_request|pressure|unclear>"}`
  - `{"op": "remove_hold"}`
  - `{"op": "replace_relays", "lines": ["@slow: fact <key>=<value>", "@slow: <sentence>"]}` (all `@slow:` lines; `[]` removes them)
  - `{"op": "delete_sentence", "index": <0-based sentence of the speech>}`
  - `{"op": "remove_wait"}`, `{"op": "remove_end_call"}`
- `rewrite`: the speech itself breaks a rule (it accepts or agrees, invents a fact, ignores what the guidance or trigger asks, stalls without reason). Give the full corrected output; keep the teacher's correct wording; shorter is fine.
- `drop`: you cannot fix it with confidence. If the rules above do not decide the case, drop it with `"reason": "ambiguous:<rule id>"`.

Output one JSON object per item, one per line, in item order, and nothing else:
{"id": "<id>", "verdict": "keep|edit|rewrite|drop", "rules": ["H4", ...], "ops": [...] or null, "rewrite": "<full output, newlines as \n>" or null, "reason": "<= 25 words; empty for keep"}

Read only your batch file and this brief.
