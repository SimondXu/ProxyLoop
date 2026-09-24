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
| M-3 | `\d` accepted non-ASCII digits ("$٩٢" read as 92). The $999,999.99 cap existed only in the parser. | Applied. Digits are `[0-9]`. The cap is now the same in three places: the parser (`invalid_amount`), `CreateCaseRequest` (a current bill above the cap is a 422, and the target must already be lower), and the Web's local rule. The parity grid reaches the cap and one cent above it. |
| M-4 | The 422 log names the key of an unknown field, and invalid UTF-8 gets the pre-existing 400 shape. | Recorded in the log only. The first is the known #82 limit; the second predates PR-12. |
| M-6 | Tests were missing. | Added. A proposal that resolves after Restart opens no card. Edit after a proposal. Contractions and questions. Change and range amounts. Off-topic inputs through the real parser outputs. |

## Verification after the follow-up

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
