# ADR-0030: The read-back loop

- **Status:** accepted (the user, 2026-10-12: "the xhigh agent proposes, the session fixes both"; principal-architect review of the session's draft)
- **Date:** 2026-10-12
- **Task:** S1-SYS-108 (D1, this PR); S1-SYS-109 (D2)
- **Builds on:** ADR-0020 (one read-back window per offer)

## Context
In the M3 battery (`runs/m3-3d90a32`, main 3d90a32), 4 of the 5 agent failures happened between "offer recorded" and "read-back confirmed".

- **Slow decided before the rep answered.**
  - Slow declined 9 offers for an incomplete read-back. When the step that declined started, the rep had heard at most one ask in 8 of the 9 cases, and none in 4. The bar's count still said "read-back asked 2×".
  - The bar opened each read-back window at the moment Slow sent the GUIDE (`slow/state.py`). Guard opens it at the line where the rep heard the ask (ADR-0020).
  - The rep's read-back comes a median 10.5 s after its policy decides to read back (p90 21 s, n=244). Slow waited 8–12 s.
  - The playbook let Slow decline when "its read-back stopped with slots not stated", and Slow read that loosely.
  - Three runs failed this way: b48f0f, cfd03b and daa474. In cfd03b and daa474 Slow declined a $62, in-mandate, no-fee offer.
- **Guard missed common ways of saying "none".**
  - Replaying `said()` on the sim rep's 252 read-back lines against the rep policy's own terms: 87% of lines were recognised in full. `changes_none` was missed in 29 of 216 lines, for example "no service changes" and "no fees, changes, or expiry".
  - In ca1906 this made the read-back stuck, Slow declined, and no approval card was ever issued.
- **FastC sometimes does not voice the ask.** In daa474 it said "I have the full terms noted". That belongs to the cp profile (ADR-0029, PLAN Now/Next 2) and is not decided here.

Real-world practice (principal-architect's review, sources in S1-SYS-108's PR):
- Reps paraphrase and sometimes omit fees.
- Regulated verification draws out each item one by one.
- Advocates confirm after the deal as well (a confirmation number and the next bill), which our `check_account` already models.

## Decision
- **D1. The status bar counts only asks the rep heard, and a reply still to come is pending.**
  - **Counting.** `slow/state.bar()` builds each revision's windows from the asks the rep heard (`slow/heard.fates`), opened at the heard line, the same windows Guard uses. Asks that were cut, cancelled or superseded before being voiced are not counted.
  - **Pending.** An ask is pending while it is sent or playing but not yet heard, or while the rep has not spoken since the last heard ask. The offers line then says "reply pending: wait for it, do not ask again", and the next-step hints do not ask again either.
  - **Stuck.** "Stuck" (two heard replies left out the same slots) is the only state whose note offers a decline, and the note now says "stuck:".
  - **Playbook.** In the full playbook, "its read-back stopped with slots not stated" becomes "the offers line says its read-back is stuck".
  - **What does not change.** `decline_offer` itself stays allowed at any time: a decline is a restriction.
- **D2. Guard reads `fees_none`, `changes_none` and `expires=none` from where a negation applies, not from phrase lists.**
  - **Unit.** The rule works sentence by sentence over closed word classes.
  - **Reach.** The negation can cover a list ("no fees, changes, or expiry"), and it also counts after a negated existence verb ("doesn't have an expiration date").
  - **Fails closed.** The statement is void, so nothing is confirmed:
    - on an exception word after the negation ("no changes except the router swap");
    - on a time qualifier after a negated expiry ("that rate won't expire after the term ends" is a price lock, not an offer without expiry);
    - on a price word near "changes";
    - on a question.
  - **Contradictions.** The existing contradiction rules (a stated one-time amount, an un-negated change word, a date) stay as they are.
  - **Freezing.** The word classes are frozen named constants. A change to them needs a stated meaning, not one more phrase.

## Acceptance
- **D1, offline.** At each of the 9 M3 read-back declines, replaying the new bar shows none stuck: 8 pending, and 1 (cfd03b, after its offer had expired) "not read back".
- **D2, offline.**
  - On the 252 M3 lines: no misses except 5 genuinely ambiguous lines, which stay unconfirmed.
  - On a hand-written negative set: no false confirmations.
  - On the next battery's rep lines, which the rule was not tuned on: misses ≤ 2% and no false confirmation, or else a design rethink.
- **Live.** The three full families, 10 runs each:
  - read-back declines while not stuck: 0;
  - X: 0;
  - A, B and S compared with M3, never pooled with it, because Slow's fingerprint changes;
  - offers that expire while an ask is pending are counted. That is the main risk: if FastC never voices the ask, Slow waits.

## Alternatives rejected
- **More `LEXICON` phrases.** Tenure needed three patches (#315).
- **Slow attests a "none" slot.** A model's belief would make an offer acceptable.
- **Approving with an unconfirmed slot on the card.** This reopens the hidden-fee trap.
- **A Guard gate on `decline_offer`.** A model must always be able to say no.
- **Canonical sim-rep wording.** That is a world change and the user's call.
- **A higher `STOP_AFTER`.** It does not fix the counting.

## Consequences
- **Contract:** none. The `readback.updated` payload is unchanged.
- **Tests:** tests that never voiced their asks now voice them. One test changes its expectation: a read-back ask superseded before it was voiced is asked again, not waited on.
- **Open for the user:**
  - U1: offers say "no expiry" but die after 180 s.
  - U2: the Mouth's check does not cover "none" terms.
  - U3: a per-slot read-back question would need a world and contract change.
  - U4: whether `expires` should stay required.
- **Not addressed:**
  - COMMITTED has no exit after the rep refuses an accept (b48f0f; Now/Next 2).
  - The tenure lever was lost in 852bd1.

## Amendment (2026-10-14, S1-SYS-115): two parser regressions
- **A fee's "no" negated the term.** "It's just 62.00 a month with no fees for a 12-month term!" (247b62 cp-18) read `term_months` as none, because "no" was within 4 tokens of "12". A negation before a months value no longer reaches it across another field's role noun (`negation.ROLE_WORDS`: fees, changes, expiry), unless "or"/"nor" lists the term under the same negation ("no fees or 12-month contract" still reads none). Money amounts keep their reach: no M3 or v2 line has that shape, and "we don't charge 55.00 a month" must still deny the price.
- **A void expiry denial became "date?" (#324).** "Those terms have no expiry date at the end of the term." (d893db cp-12, seq 408) is void (an untargeted phrase follows), and `_expires` turned it into an undated expiry: it contradicted `expires=none` and reverted o1's confirmed expiry at seq 416. A void denial now says nothing, as void fees and changes do, only when its sentence has no word of negation's `TIMES`, `BOUNDS`, `CONDITIONS` or `RESTRICTIONS` and no clause after the denial's. Otherwise it still says the offer can expire ("date?"): "doesn't expire until Friday", "no expiry date, unless you wait past Friday", "no expiry date, it runs out at the end of the quarter". A plain expiry mention with no date is still undated. No word class changed.
- **Lines (`said()` on the sim rep's read-back lines vs its intent).** v2 (232 lines): contradictions 13 → 5 (term 2 → 0; expiry 11 → 5, 6 now misses); M3 (252): expiry contradictions 8 → 7. Wrong-value statements: 0 before and after.
