# ADR-0028: The sim user's chat voice agrees with its card

- **Status:** proposed (user decision 2026-10-12, x-out-of-envelope-approval step 8)
- **Date:** 2026-10-12
- **Task:** S1-SYS-103

## Context
The world's principal has two outputs: the deterministic sim approver (its button, `env/user/approver.py`) and the SimUser's chat voice (an LLM, `env/user/simuser.py`). They share one `Approver` instance, but before this ADR the chat voice saw neither the hidden card limit (`principal.limits`) nor the card's decision. In live run `runs/20261012T043721Z-99c310` (not committed) on x-out-of-envelope-approval, the rep offered $69 and Slow sent a card. FastU told the user to review it. The approver granted it ($69 is within the hidden $72 limit). Slow queued the accept. Then the chat voice, which knew only its stated $65 budget, replied "I don't approve the $69 offer…" as a plain `user.sim`, not the task's scripted stop. Slow obeyed the user's latest words, revoked, and the case ended `no_deal`. The world had produced an unscripted mind change: the button and the chat voice disagreed. The family's intent (YAML header) is that the offer is "above the monthly limit the user states, but within what they would approve when asked". The card is the single approval channel. Unscripted stops and mind changes exist only through the task's `stop` (family x-user-mind-change).

## Decision
- **One answer.** When the sim approver decides a card or a mandate (`kernel/fence.py` `Authority._sim`), the kernel calls `SimUserChannel.decided`, which calls `SimUser.on_decided`. That appends one line to the SimUser's chat right away: before the `after_card` trigger runs and before any later reply is requested. A card gets `Card: you approved|declined these terms: <readback_text>`. A mandate gets `Card: you approved|declined these limits: at most $X a month; at most N months; at most $Y in one-time fees` (only the bounds it sets). The approver's decision logic, Guard, the fence and authority semantics, Slow, the Fast prompts and the contract do not change. The line is world-side chat state only: nothing reaches the agent's views.
- **One rule** in the SimUser's SYSTEM prompt: approvals and limits are decided only on the approval card, never in chat. The user does not approve or reject an offer in a chat reply. A `Card:` line is the user's own card answer, and their replies keep to it. Only an instruction that starts `Now, in this reply:` (the scripted stop) changes their mind.
- **The scripted stop does not change.** It is generated from `text_hint` and checked as before (stop cue, revealing the mind change, not silent, `stop: stop|mind_change`). It is still the only way the world changes the user's mind, and after a card it sees that card's line in the chat.

## Evidence
No live measurement yet (needs a live run of x-out-of-envelope-approval and x-user-mind-change). Offline: `tests/env/test_card_line.py`, `tests/concurrency/test_card_line.py`, and the `simuser_card_stop` case in `tests/env/world_requests.json`.

## Consequences
- **Contract / fingerprint impact:** none. The Fast renderer is untouched.
- **World behaviour changes.** Every SimUser request has a new SYSTEM prompt, and requests after a sim-decided card or mandate carry its line. Runs before and after this change are not strictly comparable on approval steps. The S1-SYS-70 byte snapshot (`tests/env/world_requests.json`) was regenerated for the SimUser cases. ADR-0024's recorded SimUser items no longer rebuild byte for byte under the new builder. That selection has already been made, so this only matters if it is ever re-run.
- **Data invalidated:** none trained on. World-side pilot bundles recorded before this ADR keep their old SimUser prompts.
- **Risks.** The rule is a prompt, not a check. A chat reply can still contradict the card, and that is measured, not blocked. Revisit if live runs still show unscripted chat approvals or rejections, for example with a reply check that a non-stop reply carries no stop cue.
