# PR-8a Review: scripted Fast dialogue, the disclosure gate, and the per-turn split

**Target**: `feat/pr8a-fast-dialogue` @ `5946da7` (merged with `main` @ `df733f7`)

**Spec**: `harness/context/pr8-fast-dialogue-design.md`

**Reviewer**: independent read-only `reviewer` subagent. The root orchestrator
relayed the findings and its decisions, and the implementer wrote this artifact.

**Decision**: Request Changes, for one Blocking finding (B1) and one Important
finding (I1). The root accepted all findings. B1, I1, and M1–M6 are fixed on this
branch. The gate is not merged yet, so it stays `fast-gate-v1`, and spec §2.2
carries a dated amendment. Re-review is pending.

## Findings and disposition

### B1: invisible characters and lookalike letters bypass every phrase rule

**Severity**: Blocking. **Disposition**: fixed.

The reviewer's end-to-end repro, "I a​ccepted the offer and it is
fin​alized for you.", passed the gate and was stored as an
`assistant_message`. The new code `fast_gate_non_ascii_text` refuses, on the raw
text, any non-ASCII character in category L* (letters), M* (combining marks), or
C* (format, control, private use, surrogate, unassigned). The root named Cf, Co,
Cs, and L*. The implementation also refuses non-ASCII Cc, Cn, and M*, because a
combining accent or a C1 control splits a word the same way. Non-ASCII
punctuation and symbols (an em dash, curly quotes) still pass, and every
scripted line still passes G7.

Tests:
- G2: U+200B, U+200C, U+200D, U+2060, and U+FEFF inside "accepted",
  "finalized", "deal", and "seventy" (20 cases).
- G2: a Cyrillic а in "I аccepted", a Cyrillic д, a Greek ε, a combining accent,
  and a full-width H.
- G2: an em dash and curly quotes pass.
- D-series: `test_an_invisible_character_bypass_is_withheld_end_to_end`.

### I1: common outcome and commitment phrasings were missing

**Severity**: Important. **Disposition**: fixed. This is a gap in the spec,
recorded as an amendment.

The completion rule now includes {is, are, was, has been, have been}
[now|just|already] plus the existing list. It also includes a bare consequential
participle, with or without an auxiliary: {accepted, approved, signed, agreed,
confirmed, finalized, locked [it|this|that] in}.

The commitment rule now accepts:
- first person;
- an optional contraction ('ll, 've, 'd, 'm, 're) or auxiliary;
- an optional now/just/already;
- then one of {accept, agree, approve, sign, commit, confirm, switch, cancel,
  upgrade, downgrade, purchase, pay, order, lock (it) in}.

Every listed phrasing is refused: "Your offer is accepted.", "The plan has been
approved.", "Offer accepted and signed.", "Your switch is confirmed.", "I've
confirmed the new plan.", "I have now accepted the offer.", "I just signed you
up.", "We've locked it in.", and "we'd accept".

Refusals: "I can't accept that.", "I won't accept that.", "I will not accept
that.", "I cannot sign that.", and "We don't agree to that." pass, and a test
pins them. The passive "That can't be accepted." is refused by the
bare-participle rule. That false positive is accepted because it fails safe, and
a test pins it.

### M1: a spaced percent, "percent", and a signed amount passed

**Disposition**: fixed. The gate refuses "72 %", "72 percent", "72pct",
"-$72", and "-72". A sign counts only when it does not join two words ("7-5"
is judged as two numbers).

### M2: scheme-less domains and non-http schemes passed

**Disposition**: fixed. The gate refuses any `\w+://` and any scheme-less domain
(`[a-z][a-z0-9-]*\.[a-z]{2,}` as a word). "e.g." and "i.e." pass, and so does
every scripted line. "evil[.]com" still passes; this is a recorded lexical
limit.

### M3: the report's rates were ambiguous before PR-9

**Disposition**: fixed. The committed report was regenerated.
- `fast_fallback_rate` is renamed `gate_fallback_rate`: gate fallbacks over
  applied Fast turns.
- `fallback_cause_counts`, `calls_by_role_and_result`, and
  `fast_reject_reason_histogram` count applied turns and calls only.
- Unapplied attempts are reported apart: `unapplied_model_calls`,
  `unapplied_calls_by_role_and_result`, and
  `unapplied_fast_reject_reason_histogram`.

### M4: the §5.1 claim "last in log order is the delivered attempt" was too strong

**Disposition**: fixed in the spec amendment, `turn_split.py`, and
`docs/architecture.md`. The claim holds within one process, where the Case lane
and the direct lock serialize commands. Across processes it does not hold
(R6).

### M5: a blank line split the status table

**Disposition**: fixed in `harness/context/audit-remediation-status.md`.

### M6: no test covered a gate reject on the channel path

**Disposition**: fixed. `test_a_gate_reject_on_the_channel_path_fails_closed`
checks that a gate reject raises `ModelRuntimeError`, that the state is
unchanged with no assistant event and no outbox record, that the inbox is still
`reserved`, and that the Fast trace is `REJECTED` with `fast_gate_commitment`.

### Optional: assistant-line time

**Disposition**: done. `test_api_event_loop.py` also asserts that each
assistant line's time equals its trigger's time.

## Verification after the fixes

See `harness/log/feat-pr8a-fast-dialogue.md`, section "After the review
fixes". `runtime.py` did not change, so the DB gates were not rerun.

## Re-review: Approve, then final root additions

The re-review approved the fixes. The root then added final decisions, applied
on this branch with the gate still at `fast-gate-v1` and recorded in a dated
spec amendment:

- **Important**: the bare-participle completion rule adds switched,
  cancel(l)ed, activated, processed, completed, applied, changed, upgraded, and
  downgraded. "Plan switched and old line cancelled.", "Upgraded you to
  Unlimited.", "Switched you over.", "Activated!", "Completed.", and
  "Processed." are refused.
- **Minor 1**: `fast_gate_non_ascii_text` also covers non-ASCII symbols (S*).
  "acc℮pted", "a¢¢epted", "Offer acc€pted", and "d€al" are refused.
  Typographic quotes, dashes, and the ellipsis are punctuation (P*), so they
  still pass without a separate allow-list, and so do all scripted lines and
  `BOUNDED_FAST_STATUS_TEXT` (G7).
- **Minor 2**: the gate refuses a dash-like character (U+2010–2015, U+2212,
  U+FE63, U+FF0D) directly before `$` or a digit, "($72)", and "minus 72".
- **Minor 3**: "account owner" is added to the authority rule.
- **Minor 4**: `FAST_GATE_UNICODE_DATA_VERSION = "15.0.0"`. A test asserts
  that `unicodedata.unidata_version` equals it. The report gains
  `unicode_data_version` next to `fast_gate_version`, and the committed report
  was regenerated because of that new field. The trace contract is unchanged.
- **Minor 5**: the remaining `fast_fallback_rate` mentions in the spec
  were renamed.
