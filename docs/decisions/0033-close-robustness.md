# ADR-0033: Close robustness, an optional expiry slot, and a deferred competitor lever

- **Status:** accepted (the user, 2026-10-13: "都按你的建议做")
- **Date:** 2026-10-13
- **Task:** S1-SYS-113
- **Amends:** ARCHITECTURE §9.2 (required read-back fields), §9.3 (`verify_no_deal` (b)), §9.5 (status table)

## Context
Runs timed out or were blocked for reasons that were not the agent's fault:
- **Filler after the close.** `verify_no_deal` required the rep's *last* line since the final-offer ask to match the closing cue. In 247b62 (`runs/v2-2862d54`), the rep said "That monthly price is my absolute best offer" and then "No worries at all! What can I help you with on the account today?". `finish(no_deal)` was refused at 472 s and at 483 s. The demo run 75240d timed out on the same pattern.
- **COMMITTED had no exit.** In b48f0f, 0a6cf0 and 08f079, the rep refused an accept after it was voiced ("that offer is no longer available"). `finish(escalate)` was refused "while the case is COMMITTED", and the session ran to its 480 s cap.
- **`expires` was required.** ADR-0031 keeps an offer open for the call, so `expires` binds nothing. It still accounted for about a third of Guard's none-slot misses.
- **No competitor lever.** No format could make `competitor.*` public, so `cite_competitor` was always denied, even when the user stated a quote (0b2df4: "Fibrelink is also offering a plan for 58 if that helps!"). I11 forbids *fabricated* quotes.

## Decision
1. **A close stands until it is reopened** (`guard/verify.py` `closing_at`, `reopens`). `verify_no_deal` (b) holds when a rep line since the ask matches the closing cue and no later rep line reopens it. A later line reopens the close only if it does one of these:
   - states a money amount that no recorded offer carries (`$0` aside);
   - has a `reopen` cue (`LEXICON["reopen"]`): it makes or names an offer ("I can waive", "a loyalty promotion", "how about");
   - takes the close back ("actually", "let me check").

   Filler does not reopen the close, and neither does a stated withdrawal or a line that itself matches the closing cue ("the best rate I can offer"). Slow's close line calls the same `closing_at`, so the bar and Guard cannot disagree.
2. **`COMMITTED escalate ESCALATED`.** While no evidence is recorded, `finish(escalate)` hands the case to the user. It only restricts and grants nothing. It is refused once a rep line since the accept carries a confirmation id (`says_confirmation`): then the ledger holds the commit, and the step is `check_account` → EVIDENCE_PENDING. No transition leads from COMMITTED back toward a commit. Slow's close line and its prompt give the step: tell the user that the accept was said but not confirmed, then `finish(escalate)`.
3. **`expires` is optional.** `missing_required` no longer lists it. A revision without it hashes as "no expiry" (`offer_terms`), which is what the world's ledger binds (`expires: none`). An `expires` slot that *is* recorded must still be confirmed, because a stated date still matters.
4. **Deferred: a competitor quote that the user states.** `competitor.*` facts still never go public from the user's message (#153 round 3, I11). `FORMATS` has no competitor matcher.
   - **Why parsing was dropped.** Two Tier C review rounds on PR #334 showed that parsing the user's text publishes the user's own price or a hypothetical as a quote. Examples:
     - "Fibrelink is $58 and Lumen is $80" published 80;
     - "If another company offered $60 I'd switch" published 60;
     - "Tell them a competitor offers $50" published 50.
   - **The future path is the user's explicit authorisation, not parsing.** Slow would ask, for example, "Shall I mention Fibrelink's $58 quote?". A yes would record a public authorisation fact, like `authorization.cancel_lever`, and `lever_denial` would accept it.

## Consequences
- **Not comparable with earlier runs.** Runs after this change are not pooled with earlier runs: `slow_fp` changes, and so do Guard's no-deal and read-back rules.
- **`obs` needs a follow-up from the session.** `obs/grading.closing_reply` still uses the last-line rule; the session owns it. `env/reference` still requires `expires`, which is the stricter direction.
- **Known gaps.** `reopens` reads money in digits only, so an unrecorded amount spoken only in words and without a cue does not reopen the close.
- **Code move.** The last4, holder-name and tenure formats moved from `slow/tools.py` to `slow/formats.py`, with no change in behaviour.
- **Contract:** none. `CaseStatus` values are unchanged; this adds only a transition.
