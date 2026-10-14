# ADR-0033: Close robustness, an optional expiry slot, and the user-stated competitor lever

- **Status:** accepted (the user, 2026-10-13: "都按你的建议做")
- **Date:** 2026-10-13
- **Task:** S1-SYS-113
- **Amends:** ARCHITECTURE §9.2 (required read-back fields), §9.3 (`verify_no_deal` (b)), §9.5 (status table); #153 round 3 (competitor facts never public)

## Context
Runs timed out or were blocked for reasons that were not the agent's fault:
- **Filler after the close.** `verify_no_deal` required the rep's *last* line since the final-offer ask to match the closing cue. In 247b62 (`runs/v2-2862d54`), the rep said "That monthly price is my absolute best offer" and then "No worries at all! What can I help you with on the account today?". `finish(no_deal)` was refused at 472 s and at 483 s. The demo run 75240d timed out on the same pattern.
- **COMMITTED had no exit.** In b48f0f, 0a6cf0 and 08f079, the rep refused an accept after it was voiced ("that offer is no longer available"). `finish(escalate)` was refused "while the case is COMMITTED", and the session ran to its 480 s cap.
- **`expires` was required.** ADR-0031 keeps an offer open for the call, so `expires` binds nothing. It still accounted for about a third of Guard's none-slot misses.
- **No competitor lever.** No format could make `competitor.*` public, so `cite_competitor` was always denied. This held even when the user stated a quote (0b2df4: "Fibrelink is also offering a plan for 58 if that helps!"). I11 forbids *fabricated* quotes, and a quote the user states is not fabricated.

## Decision
1. **A close stands until it is reopened** (`guard/verify.py` `closing_at`, `reopens`). `verify_no_deal` (b) holds when a rep line since the ask matches the closing cue and no later rep line reopens it. A later line reopens the close only if it does one of these:
   - states a money amount that no recorded offer carries (`$0` aside);
   - has a `reopen` cue (`LEXICON["reopen"]`): it makes or names an offer ("I can waive", "a loyalty promotion", "how about");
   - takes the close back ("actually", "let me check").

   Filler does not reopen the close, and neither does a stated withdrawal or a line that itself matches the closing cue ("the best rate I can offer"). Slow's close line calls the same `closing_at`, so the bar and Guard cannot disagree.
2. **`COMMITTED escalate ESCALATED`.** While no evidence is recorded, `finish(escalate)` hands the case to the user. It only restricts and grants nothing. It is refused once a rep line since the accept carries a confirmation id (`says_confirmation`): then the ledger holds the commit, and the step is `check_account` → EVIDENCE_PENDING. No transition leads from COMMITTED back toward a commit. Slow's close line and its prompt give the step: tell the user that the accept was said but not confirmed, then `finish(escalate)`.
3. **`expires` is optional.** `missing_required` no longer lists it. A revision without it hashes as "no expiry" (`offer_terms`), which is what the world's ledger binds (`expires: none`). An `expires` slot that *is* recorded must still be confirmed, because a stated date still matters.
4. **A competitor quote that the user states is a lever** (`slow/formats.py`, moved out of `slow/tools.py`).
   - `competitor.price_usd` goes public only when the user's own message states the amount as a price, in digits or words ("$58", "58 dollars", "fifty-eight bucks", "a plan for 58"). It must not be another unit (months, GB, %).
   - The amount's clause must also name a competitor: the recorded `competitor.name`, a generic competitor ("another provider", "a competitor"), or a quote verb with a capitalised name that is neither the company nor another recorded fact ("Comcast quoted me $55").
   - A negated clause never publishes ("I don't have any other quote"), nor does a clause with the user's own price or limit ("I pay 85", "$65 tops", "accept the $62 offer").
   - `competitor.name` goes public only when it appears as the user wrote it, capitalised, and is neither the company's name nor another recorded fact's value.
   - `_leaks` still applies: a protected value or a mandate bound never goes public.

## Consequences
- **Not comparable with earlier runs.** Runs after this change are not pooled with earlier runs: `slow_fp` changes, and so do Guard's no-deal and read-back rules.
- **`obs` needs a follow-up from the session.** `obs/grading.closing_reply` still uses the last-line rule, and `obs/ladder.REACHABLE` still omits `cite_competitor`. The session owns both. `env/reference` still requires `expires`, which is the stricter direction.
- **Known gaps.** `reopens` reads money in digits only, so an unrecorded amount spoken only in words and without a cue does not reopen the close. If Slow mis-keys a user's message as a competitor quote, the guards above are the only check.
- **Contract:** none. `CaseStatus` values are unchanged; this adds only a transition.
