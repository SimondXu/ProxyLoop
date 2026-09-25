# PR-12 stateless intake review

**Target**: `feat/pr12-stateless-intake` @ `63d1d00` against `main` @ `04a8ed5`
(spec `harness/context/pr12-stateless-intake-preflight.md`).

**Reviewer**: independent read-only `reviewer` subagent. It ran scratch probes
(`rev-pr12/probe.py`, `probe2.py`, `probe3.py`, `route.py`, `timing.py`) against
the parser and the route.

**Recommendation**: Request Changes. There is no Blocking finding. The main
invariant holds: a Case is created only on the explicit "Create fictional Case"
click, with the typed facts. The problem was that the parser filled in values
where the spec promised a clarification, and some of those values were wrong.
The root decided the principle "any uncertainty becomes a clarification, never a
guessed value". The root passed the dispositions below to the implementer, who
wrote this file from the root's message. The parser changes are recorded as
`intake-parser-v1` rule amendments in the spec, with no version bump because the
branch is unmerged.

## Findings and disposition

| # | Finding | Disposition |
|---|---|---|
| I-1 | Negations and questions became `true`: "hotspot isn't required", "I won't need hotspot", "hotspot doesn't need to stay", "financing isn't staying the same", "I can't keep financing the same", "Can I keep my hotspot?", "Keep the hotspot? Nope", "I need a hotspot for work but honestly I'd drop it", "keep financing unchanged but I want to end it". The card also labelled read values "Confirmed". | Applied. These now count as negation: `\w+n't` and the apostrophe-less forms, `nope`, `nah`, `cannot`, `end`. Hedges also make a feature ambiguous: `unless`, `if`, `optional`, `maybe`, `rather`, … A sentence ending in `?` or starting with a question form makes its features ambiguous. A later clause that negates or changes something without naming a feature makes the most recently named feature ambiguous. All nine inputs, plus five more, yield `ambiguous` (pytest). In the Web, a read value shows "Read from your message", never "Confirmed", until the consumer supplies it or chooses Create (vitest). |
| I-2 | Amounts were guessed. Change amounts ("save $20", "$75 off", "by $12", "at least $80 less") took a role. Ranges ("between $75 and $80", "$70 to $80") and history ("went up to $92", "jumped from $85 to $110", "went from $80 to $92") were read as targets. A second amount with no cue ("… but ideally $80") was dropped silently. | Applied. An amount has no role when it is a change amount, a range, after a price-history verb, inside a question, or has no cue. Any amount with no role makes both amount fields `ambiguous`. `from $X to $Y` without a history verb stays current → target. 18 sentences are tested, including "my bill went up to $92". |
| I-3 | In the Web, a money edit dropped both amounts' rule codes. Example: target $70 `below_fixed_offer`, then current edited to $95. The target's code disappeared while its rule still failed, leaving Create disabled with no prompt. | Applied. The other amount keeps its rule code until its own rule passes with the new value. The next prompt also covers any amount the local rules still reject. Vitest: target $70 → edit current to $95 → the target is re-prompted; $80 then enables Create and sends 9500/8000. A second vitest: `target_not_below_current` is released once the current bill is raised. |
| M-1 | The card opened on clarifications alone, for off-topic text. | Applied. The card opens only if a value was read or the scope gate passes. The five off-topic inputs, with their real parser outputs, are in `apps/web/app/components/intake-offtopic-proposals.json`, pinned by pytest and used by vitest. |
| M-2 | The failure reply could say "Nothing was created." twice. | Applied (vitest asserts no repeat). |
| M-3 | `\d` accepted non-ASCII digits ("$٩٢" read as 92). The $999,999.99 cap existed only in the parser. | Applied. Digits are `[0-9]`. The cap is now the same in three places: the parser (`invalid_amount`), `CreateCaseRequest` (a current bill above the cap is a 422, and the target must already be lower), and the Web's local rule. The `CreateCaseRequest` cap is a **root decision**, not the reviewer's recommendation; it tightens the create contract, which the re-review judged safe. The parity grid reaches the cap and one cent above it. |
| M-4 | The 422 log names the key of an unknown field, and a body that is not valid UTF-8 gets a 400 shape. | Recorded in the log only. Both behaviours predate PR-12. The privacy test does not cover the extra-key case: the key a client chooses can appear in the server log. |
| M-5 | Quadratic backtracking cost (found in the re-review together with I-A). | See I-A below. |
| M-6 | Tests were missing. | Added. A proposal that resolves after Restart opens no card. Edit after a proposal. Contractions and questions. Change and range amounts. Off-topic inputs through the real parser outputs. |

## Verification after the follow-up

The DB gate counts, the Browser run, and the red counts below are
**implementer-reported**.

- Red against the pre-review code: 32 of 219 pytest items fail against the
  `63d1d00` parser. 10 of 144 workspace vitest cases fail against the
  pre-review component.
- The following exited 0: `make lint`, `make typecheck`, `make test` (runtime
  1813 passed / 63 skipped; ML 397 / 1 skipped), `make web-check` (vitest 218),
  and `make preflight` (gated-skip pin 63).
- DB gates were rerun serially after the change, because `CreateCaseRequest`
  gained the cap: `postgres-check` 38, `phase05a-check` 53, `phase06b1-check` 56.
- The Browser journey passed against the real durable Runtime, with details in
  the log.

## Re-review (Request Changes: one Important finding, I-A)

| # | Finding | Disposition |
|---|---|---|
| I-A (with M-5) | `_TO_AMOUNT_BEFORE` and `_FROM_TO_BEFORE` had adjacent `\s*…\s+`, and `_role` ran them on the whole text before every amount. The cost was quadratic: `("from 1" + " "*1300 + "$5 "*231)[:2000]` took about 1.6 s. | Applied. The patterns no longer have adjacent optional whitespace and see only the right-stripped last 48 characters. More than 8 amounts make both amounts ambiguous without reading each one. A timing regression test covers spaces, tabs, repeated "＄⑳", "$1-", and long-whitespace cases under the 8-amount cap, each asserted < 250 ms. Implementer-measured: 1.7 s → ≤ 1.8 ms (see the log). The spec's "every regex is linear" claim is corrected. |
| UX (accepted) | Common target cues. Lowering requests, including as a question. "Actually … both" and "Actually no." should reach every feature. The card should open on an amount clarification. "confirmed" should be dropped from the copy. The non-422 reply should say "Nothing was created." | Applied, with tests for each new phrasing. |
| Limits (root) | An unrelated later negation makes the last feature ambiguous. "from $X to $Y" with no verb is read as current → target. | Recorded in the spec; no change. |

## Later rounds (after the re-review)

The root recorded each round as a dated spec amendment
(`harness/context/pr12-stateless-intake-preflight.md`) and a log section
(`harness/log/feat-pr12-stateless-intake.md`). Every change stayed under the
name `intake-parser-v1`, because nothing under that name was merged.

| Round | Target | Findings | Disposition |
|---|---|---|---|
| Root decision (3rd amendment) | `0b589f4` | Off-topic text with money opened the card ("vacation for $2,000"). | Card rule (c): an amount clarification opens the card only with a closed-list bill or payment cue. Bare `plan` is not a cue (option A); "My plan went up to $92" gets the scope reply, a documented limit. |
| Focused re-review (4th amendment) | `0b589f4` | **I-1** bare `get` made non-lowering questions read values. **M-1** per-clause doubt scan; NFKC expansion. **M-2** target-first order decided mixed cues. **M-3** missing retractions. **M-4** `unsupported_currency` opened the card. **M-5** the intake failure copy used Case or Runtime wording. | Applied. `get` only with a lowering word, not before `than`. A 4000-character cap after NFKC (all fields `missing`). Doubt is computed per sentence. Retractions added. M-4 and M-5 applied in the Web. The implementer's first M-2 reading ("nearer current cue") was rejected by the root, because it made common target phrasings ambiguous. It was replaced by the root's tiered cues (`6f34ff0`). |
| Final review (5th amendment) | `6f34ff0` | **I-1** the 48-character tail hid distant history verbs, so "went down … from $95 to $85" was read. **I-2 / M-b** role cues outside the tail were lost. **M-a** more retractions. **M-c** per spec. | Applied at `7d684ed`. History and role cues read the whole clause; the tail is kept only for the end-anchored patterns. Retractions extended. The implementer also removed its own `comes to` exclusion, which had made "I hope it comes to $75" a guessed current bill. M-c: no change. |
| Final verification | `7d684ed` | The fixes are confirmed. One guessed-value source was left: `like it (to be\|at)` ("I don't like it at $92" → target $92). | Deleted (root decision). The reviewer's fuzz, seeds 1–3 against `0b589f4`, finds 0 readings that gain or change a value (100,000 inputs per seed). |

**Final verdict: Approve.** The reviewer approved once the
`like it (to be|at)` branch was removed. No finding is open. The documented
limits in the spec remain: over-asking and fail-safe misreadings, such as "No
rush", "Never mind the rush", "My plan went up to $92", "I'd be happy at
$75", and "My bill comes to $92".
