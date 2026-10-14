# ADR-0032: The sim rep answers like a real retention rep

- **Status:** accepted (the user, 2026-10-13: "批准世界改动")
- **Date:** 2026-10-13
- **Task:** S1-SYS-112
- **Amends:** ADR-0021 D4 (the rep voices each decision of a block: now one reply per caller turn) and the Ear's verified act order (S1-SYS-95).

## Context
A read-only audit of 77 live bundles (principal-architect, 2026-10-13) found that runs were failing for reasons in the world, not in the agent:
- **Timing.** The rep's Ear and Mouth calls were in flight for a median 68 % of call time. The median wait from an agent utterance to the rep's reply was 19.9 s (p90 41.7 s, n = 1,826). The accept line waited a median 25.6 s before it was voiced (max 58.9 s).
- **Turn-taking.** The rep answered each heard utterance separately:
  - 45 % of rep lines (841 of 1,868) were the 2nd or later reply to one heard block.
  - 29 % (551) were "Sorry, how can I help with your account?", said in reply to "Thank you" or "I'll check with Marcus".
  - In 50 of 77 runs the rep said "I still need to verify" and "you're verified" in the same turn.
- **The Ear's verified order.** It ranked ask_readback and decline above the levers, so 12 of 171 tenure cues were lost (10 heard as ask_readback, 2 as decline; graded E in e5802a and 852bd1).
- **Silence strikes** added up over the whole call, so three check-ins far apart hung up a caller who had answered each one.
- **cp-direct-discount.** The info_only ladder lacked the hidden `changes_none` and `expires` terms that the other families have, so its read-back could never be confirmed (0 of 10 in M3).

## Decision
1. **One reply per caller turn** (`env/counterparty/simrep.py` `voiced`). Every decision is still emitted (`rep.policy`, `rep.commit_heard`, `ledger.write`), so decisions, commits, strikes, rungs and the ledger do not change. Only what is voiced changes:
   - A commit is always voiced, and `offer_expired` stays silent.
   - An intent equal to a later one in the turn is voiced only at the later one (D4 extended from runs of equal intents to any repeat).
   - `ask_identity` is dropped when the same turn passes identity (`how_can_help`).
   - A filler (`clarify`, `ack`) is dropped when the turn has another reply. A turn of fillers only voices its last one.
   - A strike whose decision is not voiced cites its `rep.policy`, as D6 already allowed.
2. **An ack once an offer exists.** Smalltalk or `other` after any offer is made gets the new public intent `ack` ("Sure, take your time."). Before any offer, it is still `clarify`. The Mouth's fidelity check is unchanged: the ack line has no values.
3. **One turn's Mouth calls run concurrently** (`Mouth.say_all`). Each line's `rep.mouth` is emitted in line order. The first failure cancels the other calls and propagates as itself (`LLMUnavailable`, `WorldError`). The regenerate-then-template rule per line is unchanged.
4. **Verified Ear order:** accept, decline, then cite_competitor, cancel_intent, tenure, then ask_readback, ask_discount, then provide_fact, then the rest. Accept and decline stay first (CONFIRM safety), and ask_discount stays after ask_readback. The unverified order (codebook v1) is unchanged.
5. **cp-direct-discount (version 2):** every rung of the info_only ladder gains `changes_none: "true"` and `expires: none`, as in the full variant. `tasks/families/v1/` is untouched.
6. **Silence strikes count only in a row.** Any heard act starts the silence count again (`Policy.step`). The hang-up comes at `patience.strikes` silence strikes in a row plus hold strikes. Hold strikes (S1-SYS-20/28) and identity strikes never start again. `timer_strikes` stays the total, equal to the `chan.strike` events.

## Evidence
- `tests/env/test_rep_realism.py`: the voicing rules, the ack before and after an offer, the concurrent Mouth (a gate that answers only once every call of the turn is in flight, answering in reverse order), a dead Mouth that aborts loudly with no `rep.mouth`, the Ear order, the family terms in both modes, and the silence reset.
- The equality test (`test_the_collapse_changes_only_the_rep_lines`) covers ADR-0021's 15 T5 sequences and 3 realism sequences. It replays each run's own Ear acts through a bare `Policy`, with no voicing. Decisions, commits, ledger writes, strikes, rungs and the policy state are equal. Only the number of rep lines falls.
- Offline estimate (scratch script, not committed) on `runs/m3-3d90a32` + `runs/v2-2862d54`. It applies `voiced` to the logged decisions of each block: 71 bundles, 1,720 rep lines → 1,179. The audit's own simulation gave 1,868 → 1,314.

## Consequences
- **Contract / fingerprint impact:** none. The `ack` intent kind, the Ear system prompt and the Mouth are world-side, not the renderer.
- **Data invalidated:** v2 runs from after this change are not pooled with earlier runs (M1–M3, `runs/v2-2862d54`, or v2 runs before this merge). The next battery re-measures all four families.
- **Migration:** recorded bundles keep their old `rep.mouth` lines as history, and nothing replays them through the Mouth. The world-request snapshot (`tests/env/world_requests.json`) carries the new verified order.
- **Risks and what would make us revisit this:**
  - A `greet` line beside `how_can_help` in one turn is still voiced (it carries the company opening).
  - A rep that never answers a filler may read as curt.
  - The live effect on reply latency is unmeasured until the per-family smokes run.
