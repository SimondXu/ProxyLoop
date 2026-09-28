# ADR-0020: One read-back window per offer

- **Status:** accepted (main-root decision D1, 2026-09-28, §0.5a, on the architect's adversarial analysis)
- **Date:** 2026-09-28
- **Task:** S1-SYS-62

## Context
- **Guard was stricter than the reference.** Guard anchored a read-back to one offer *revision*: only rep lines after a `guide(ask_readback)` for that revision could confirm it. In run 21988c the rep's answer to the r1 ask stated all five terms; Slow recorded r3 from that answer, and r3 then needed a second ask (it was declined before a later reply confirmed it). `env/reference.py` accepts one answer.
- **Carry-over is unsound.** r2 in 21988c dropped price and term, so revisions are not add-only, and copying confirmations across revisions confirms nothing. Carry-over also fails adversarially: a stale price after "actually $80", a package change through an added slot, an expiry change.
- **A prompt fix cannot help.** Terms first revealed in the read-back force a new revision, and so a second ask, whatever Slow is told.

## Decision
The per-revision rule stays. One more way to confirm is added (`guard/readback.py`). Revision r of offer o is confirmed by an ask A for o (any revision, in the same cp call) when all four hold:
- **W1, stable since the ask:** every rep clause at or after A that states a field of r states exactly r's value, including the implied completeness flags (`fees_none` is false if r lists a fee, `changes_none` is false if r lists an applied change, when r has no such slot).
- **W2, no change across the ask:** the rep's last statement of each field before A, if any, equals r's value.
- **W3, stated together:** every slot is stated at or after A, and at or after the latest line at which any slot was first stated after A.
- **W4, all or nothing:** one ask confirms every slot or none, never a mix of asks.

Statuses are recomputed from the transcript on every `readback()`, never copied, so a later contradiction reverts them. Neither the revision bookkeeping nor the authority epoch is a condition. `slow/tools.py` records every ask per offer with its call (`chan.opened{cp}` count) and passes Guard only the asks for that offer in the current call. `slot_statuses(o, lines, asked_at)` without asks is the strict rule alone, so `slow.state.restated` (V4) is unchanged.

## Evidence
- `tests/guard/test_readback_window.py` (nine negatives, 21988c's shape and a hidden fee revealed on read-back) and `tests/slow/test_readback_window.py` (another offer's ask, an earlier call's ask, a reverted status). Dropping any of W1 (slots), W1 (implied flags), W2, W3, W4, the same-call filter or the per-offer filter turns at least one negative red (S1-SYS-62 PR).
- Offline replay of runs 21988c, e6ada1 and 527345 (S1-SYS-62 PR): only 21988c changes. Its r3 is confirmed when recorded, with no second ask; before, it never was. e6ada1 (r1 lacks required fields) and 527345 (no read-back reply) are unchanged.

## Consequences
- **Contract / fingerprint impact:** none. `readback.updated` keeps its payload; no renderer, view or event change.
- **Metrics:** `readback_completion` and `readback_false_confirm` (EVAL §7) change meaning at this commit. Runs are labelled by their manifest `git_sha`: before the S1-SYS-62 merge, "per-revision read-back"; from it on, "per-offer window". The two are never pooled in one number without that label.
- **Data invalidated:** None: readback_completion and readback_false_confirm have never been computed (eval/metrics.py REASONS lists both as unavailable), so no data was seen under the old meaning; this ADR defines the metric before its first computation.
- **Risks and what would make us revisit this.** W1's implied flags reject a truthful "we switch you to X, no other changes" under the window (the per-revision rule still confirms it after its own ask). Lexicon errors now reach one more path; the Ear audit measures them. Revisit if `readback_false_confirm` rises on "per-offer window" runs.
