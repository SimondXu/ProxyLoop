# PR-12 preflight: stateless intake (Stage 3)

Bounded change under decisions 16–20 (`harness/context/audit-remediation-decisions.md`),
build plan row PR-12 (`harness/context/build-plan-to-complete.md`). Branch
`feat/pr12-stateless-intake` from `origin/main` @ `04a8ed5` (#96, PR-10 merged).
Written 2026-09-24. Tags: **[O]** observed in code, **[P]** proposed here.

## Sources

- Build plan PR-12: "stateless `POST /intake/proposals` with a deterministic parser;
  a Web card replaces the wizard"; DoD item 2 "free-text intake → typed card →
  confirmed Case → …".
- `audit-remediation-status.md` §5 item 3: stateless intake, so the Case invariant
  "goal is consumer-confirmed" stays typed.
- Target architecture proposal §3 step 1–2, §4 row "Intake" (`ConsumerGoalProposal`
  is **not** canonical: an API request/response model in `services/api`), §5
  (`CaseCommandType.INTAKE_PROPOSAL` is not added), §9 (the returned typed goal is
  a card the user edits or confirms; only confirmed typed facts create the Case),
  §12 Q5 (**stateless**).
- [O] `runtime/services/api/src/proxyloop_api/app.py`: `CreateCaseRequest` (strict
  USD; current > 7200 minor; 7200 ≤ target < current; both booleans the literal
  `true`), the content-free 422 handler (#82), operation records, the browser
  allow-list, the B2-8 threadpool/lock.
- [O] `runtime/packages/case_runtime/src/proxyloop_case_runtime/runtime.py`
  `_case_with_intake` repeats the same rule (not touched: `runtime.py` is reserved
  for PR-9a/PR-13).
- [O] `apps/web/app/components/conversation-workspace.tsx`: the wizard asks, one
  composer turn each, for the current bill, the target, hotspot, and financing,
  then shows a Draft Task Brief whose "Create fictional Case" sends exactly the
  four `CreateCaseRequest` fields. `isSupportedMobileBillIntent` gates the first
  message; `parseUsdMoney` and `parseBooleanFact` parse each field turn.

## Decision 1 — the endpoint contract [P]

`POST /intake/proposals`, stateless, in `services/api`.

Request (`IntakeProposalRequest`, `extra="forbid"`, strict):
`{"text": str}`, 1 ≤ length ≤ 2000 characters. Anything else → the existing
content-free 422 `{"detail": {"code": "request_invalid", "message": "request
rejected"}}`; the server log gets field locations and error types only (never the
value), exactly as today.

Response 200 (`IntakeProposal`):

```json
{
  "parser": "intake-parser-v1",
  "proposal": {
    "current_monthly_total": {"amount_minor": 9200, "currency": "USD"} | null,
    "target_monthly_total": {"amount_minor": 7500, "currency": "USD"} | null,
    "mobile_hotspot_required": true | null,
    "device_financing_change_forbidden": true | null
  },
  "clarifications": [{"field": "<one of the four keys>", "reason": "<code>"}]
}
```

- The four proposal keys are exactly the `CreateCaseRequest` keys, so a confirmed
  card maps 1:1 to the create body. Booleans are `true` or `null` because the
  create path accepts only the literal `true`.
- `clarifications` holds at most one entry per field, in the key order above.
  Closed reason codes: `missing`, `ambiguous`, `invalid_amount`,
  `unsupported_currency`, `below_fixed_offer`, `target_not_below_current`.
  A value is returned together with a clarification only for the two value rules
  (`below_fixed_offer`, `target_not_below_current`); every other reason has a
  `null` value.
- The response never contains the text or any substring of it: only Money,
  booleans, and closed codes.
- `parser` names the rule set; any rule change bumps it.

Stateless: no Case, no command, no repository or Runtime call, no Temporal
dispatch, no model call, no persistence, no trace. The same handler runs in direct
and Temporal mode. It is a sync `def` handler (FastAPI runs it in the threadpool,
B2-8); it takes no lock because it touches no shared state.

The parser is deterministic and model-free in **every** adapter mode. A
model-backed intake (proposal §3 "Runtime calls Slow") is not built: decision 17
keeps Slow scripted, and a model call would add a trace and a spend path. If it is
ever wanted, it is a new decision and a new parser version.

## Decision 2 — the parser and its limits [P]

A pure module `proxyloop_api/intake.py`: `propose_intake(text) -> IntakeProposal`.
Standard library `re` + `unicodedata` only (NFKC, `’` → `'`); no import of
`case_runtime` or `agent_core`. The input is ≤ 2000 characters. The regexes
are not all provably linear. The re-review amendment below bounds the work
instead: no pattern has adjacent optional whitespace runs; the end-anchored
patterns see only a 48-character tail; at most 8 amounts are read one by one.
A timing test holds adversarial 2000-character input under 250 ms (well under
1 ms measured locally).

Clauses: the text is split at `; ! ?` and newlines, at `.`/`,` followed by
whitespace or the end (so `$1,092.50` stays whole), and at the words `and`/`but`.
Cues are read inside one clause only.

**Amounts.** A money mention is `$N` or `N USD` / `N dollar(s)` / `N bucks`. `N`
is strict: plain digits or comma-grouped thousands, at most two decimals, one
trailing sentence `.` or `,` dropped; at most $999,999.99. A mention that is
negative (`-$5`, `$-5`), a range (`$70-75`, `$70–$75`), glued to a letter
(`$92k`), or otherwise not strict is `invalid_amount` for its role. Bare numbers
("my bill is 92") are not read. Any foreign-currency marker in the text (`€ £ ¥`,
`EUR`, `euro(s)`, `GBP`, `CAD`, `AUD`, `JPY`, or a letter-prefixed `$` such as
`A$`, `US$`) makes both amount fields `unsupported_currency` with no value.

Each mention gets a role:

1. The words right after it: `bill`, `plan`, `now`, `currently`, `today` →
   current; `or less/lower/below/under/cheaper`, `max(imum)`, `tops`, `target`,
   `goal`, `at most` → target.
2. Otherwise the clause text before it (from the clause start or the previous
   mention): a target cue (`to`, `under`, `below`, `target`, `goal`, `at most`,
   `no more than`, `less than`, `lower than`, `cheaper than`, `max(imum)`,
   `reach`, `want`, `aim`, `budget`) → target; else a current cue (`currently`,
   `current`, `now`, `pay/paying/paid`, `is/are/was`, `cost(s/ing)`,
   `charge(d/s)`, `spend(ing)`, `from`, `bill`, `at`) → current; else unresolved.

Per role: any invalid mention → `invalid_amount`; two different valid values →
`ambiguous`; one value (repeats allowed) → that value. An unresolved mention makes
only a still-empty field `ambiguous`; no mention at all → `missing`. Then the
value rules, the same as `CreateCaseRequest`: current ≤ $72.00 →
`below_fixed_offer`; target < $72.00 → `below_fixed_offer`; both present and
target ≥ current → `target_not_below_current` on the target. A parity test pins
"no amount clarification" ⇔ `CreateCaseRequest` accepts, over a grid of pairs.

**Keep / never-change (closed vocabulary).** In each clause that names the
feature, the keep phrases are removed (longest first); the feature is `true` only
if a keep phrase was present and no negation or change word remains; any other
clause naming it makes it `ambiguous`. No clause names it → `missing`.

- Mobile hotspot: terms `hotspot`, `hot spot`, `mobile hotspot`, `tethering`.
  Keep phrases `keep`, `need(s)`, `require(d/s)`, `must have`, `must keep`,
  `retain`, `preserve`, `stay(s)`. Residual words that make it ambiguous: `no`,
  `not`, `don't`, `do not`, `never`, `without`, `drop`, `remove`, `cancel`,
  `lose`, `disable`, `off`, `stop`, `rid`.
- Device financing: terms `financing`, `finance`, `device/phone financing`,
  `device/phone payment(s)`, `device/phone installment(s)`, `installment plan`.
  Keep phrases `don't change`, `do not change`, `never change`, `not change`,
  `no change(s)`, `without changing`, `don't touch`, `do not touch`,
  `unchanged`, `untouched`, `keep`, `leave`, `same`, `as is`, `alone`. Residual
  words that make it ambiguous: the hotspot list plus `change(s/d)`,
  `modify`, `switch`, `pay off`, `payoff`, `end`, `refinance`, `restructure`.

Deliberate limits, not bugs: English only; no number words ("ninety-two"); no bare
numbers; no inference from "a lower bill" to a target; a keep phrase across an
`and` ("keep my hotspot and device financing") leaves the second feature
`ambiguous`; a double negative ("never lose my hotspot") is `ambiguous`. Every
limit fails toward a clarification, never toward a value the consumer did not
write, and the consumer confirms every value on the card.

## Decision 3 — the Web card replaces the wizard [P]

- The first composer message goes to `proposeIntake(text)` in `runtime-client.ts`
  (strict response parse: exact keys, USD safe-integer Money, `true | null`,
  closed field and reason codes; otherwise the existing "invalid snapshot" error).
  Longer than 2000 characters is refused locally without a request.
- If the proposal found no fact at all and `isSupportedMobileBillIntent(text)` is
  false, the existing "only supports lowering a fictional mobile bill" reply is
  shown and nothing else happens. Otherwise the Draft Task Brief card opens,
  filled from the proposal. This keeps today's scope gate for off-topic text while
  a full sentence that the gate would miss ("my bill is $92, target $75") still
  opens the card.
- The card shows each field's value or its clarification ("Missing", "Needs
  clarification · …", or the value with the rule it breaks). The first field with a
  clarification becomes the active field and its prompt is asked; the consumer
  answers in the composer exactly as today (`parseUsdMoney`, `parseBooleanFact`,
  `intakeValueError` unchanged) or uses Edit on any row. A field's server
  clarification is dropped once the consumer supplies that field.
- "Create fictional Case" stays disabled until the four typed values pass the
  unchanged local rules; only that click calls `createCase` with the typed facts.
  The Case is therefore created only from consumer-confirmed typed facts: the
  invariant stays typed and `create_case` is unchanged.
- The sequential step-by-step prompting from an empty draft is gone; step prompts
  remain only for fields the proposal could not fill.

## Decision 4 — privacy of free text [P]

The text is never logged, never echoed, never persisted:

- API: the handler logs nothing; the operation record is the existing allow-list
  (route, status, latency, categories; no body). A 422 logs field locations and
  error types only (existing handler). The response carries no text. An internal
  error is the existing content-free 500.
- Web: the text is sent once to the local Runtime; the browser envelope
  (`proxyloop.runtime:v1`) still stores only the locator, confirmed typed facts,
  and one pending command; the text stays only in the in-memory transcript bubble,
  as today.

## Decision 5 — no contract change [P]

None. `IntakeProposalRequest` / `IntakeProposal` are API-local pydantic models
(proposal §4 "Intake" row); Money is reused as a value type. No `CaseCommandType`,
no `CreateCaseRequest` change, no browser-projection change, no `runtime.py`
change, no DB-gated test (the gated-skip pin is unchanged).

## Red tests and acceptance criteria

Python, `tests/integration/test_stateless_intake.py`:

1. Parser table: full sentence → four values, no clarifications; `from $92 to $75`;
   `my $92 bill down to $75`; `92 dollars` / `75 USD`; missing fields; two target
   values → `ambiguous`; unresolved amount → `ambiguous`; `$70-75`, `-$5`, `$92k`,
   `12.345` → `invalid_amount`; `€92` / `A$92` → `unsupported_currency`; `$70`
   current → `below_fixed_offer` with value; target ≥ current →
   `target_not_below_current`; hotspot and financing keep / negated / bare /
   `no change, but please modify device financing` → `ambiguous`.
2. Parity: over a grid of (current, target) the parser has no amount clarification
   iff `CreateCaseRequest` accepts the pair.
3. Determinism: the same text twice gives byte-identical JSON.
4. Route: 200 with the typed body in direct and in Temporal mode (a failing
   Temporal client proves no dispatch); the repository holds no Case afterwards.
5. Privacy: a marker in the text appears in no response body, no log record at any
   level, and no operation record, for a 200 and for a too-long 422; the 422 body
   is the content-free body; an extra field is 422.

Web, vitest:

6. `runtime-client.test.ts`: `proposeIntake` posts `{text}` to
   `/api/runtime/intake/proposals`; a malformed response (extra key, non-USD, a
   `false` boolean, an unknown reason) is rejected.
7. `conversation-workspace.test.tsx`: one sentence fills all four rows and enables
   Create without step prompts; `createCase` receives exactly the proposed typed
   facts only after the click; a partial proposal prompts only the missing field;
   an ambiguous/invalid field shows its clarification and blocks Create until
   answered; off-topic text with no facts keeps the scope reply; a proposal
   failure creates nothing; the text is not in localStorage.

Acceptance: all red tests fail on `main` and pass on the branch; every existing
test passes (the wizard-specific helper is rewritten to the card flow); `make
lint`, `make typecheck`, `make test`, `make web-check`, `make preflight` green;
Browser check and DB gates reported "ready for DB" (the lane runs them).

## Docs

`docs/architecture.md` (Experience Layer and Control Plane), `CONTEXT.md` (new
term **Intake Proposal**, via the domain-modeling procedure), status §0 PR-12 row
and §5 item 3, log `harness/log/feat-pr12-stateless-intake.md`.

## Limits

- The $72 rule now has four copies (API `CreateCaseRequest`, `runtime.py`, the
  Web, the parser); the parser copy is pinned to `CreateCaseRequest` by the parity
  test. One owner would need `runtime.py` (reserved) — left for PR-13 or later.
- The Web scope gate (`isSupportedMobileBillIntent`) is a second free-text reader
  in the browser; it decides only whether an empty proposal is off-topic.
- The parser is a lexical floor, English only; its misses become clarifications.
  One known misreading is not a clarification: `to` is a target cue, so "my bill
  went up to $92" proposes $92 as the target. The card shows it and the consumer
  corrects it before creating anything.

## Amendment 2026-09-24 — review (Request Changes): `intake-parser-v1` rule amendments

The independent review found no Blocking defect; the create-only-on-click
invariant holds. It found values filled in where this spec promised a
clarification. Root decision: **any uncertainty becomes a clarification, never a
guessed value.** The branch is unmerged, so the rule set keeps the name
`intake-parser-v1`; these amendments replace the matching rules above.

- **I-1 features.** Negations include `\w+n't` contractions and their
  apostrophe-less forms (`isnt`, `cant`, …), `nope`, `nah`, `cannot`, `end`;
  hedges (`unless`, `if`, `optional`, `maybe`, `perhaps`, `probably`, `rather`,
  `ideally`, `whatever`) also make a feature `ambiguous`. A sentence ending in
  `?`, or starting with a question form ("can I", "is my", "what", …), makes
  every feature it names `ambiguous`. A clause that names no feature but holds a
  negation or change word ("Nope", "I'd drop it", "I'll pay off the phone")
  makes the most recently named feature `ambiguous`. Web: a value read from the
  message is labelled "Read from your message", never "Confirmed", until the
  consumer supplies it or chooses Create.
- **I-2 amounts.** An amount has no role when it is a change amount (`save`,
  `cut`, `by`, `off`, `between`, `at least`, `more than` nearer than any role
  cue; or followed by `off`/`less`/`cheaper`/`lower`/`savings`), a range
  (`$70 to $80` without `from`, `between … and …`), after a price-history verb
  (`went`, `gone`, `moved`, `changed`, `jumped`, `raised`, `rose`, `increased`,
  `climbed`, `hiked`, …), inside a question, or has no cue. **Any amount with no
  role makes both amount fields `ambiguous`** (replacing "an unresolved mention
  makes only a still-empty field ambiguous"). `from $X to $Y` without a history
  verb stays current → target. "my bill went up to $92" is now `ambiguous`, not
  a $92 target (the earlier known limit is closed).
- **I-3 Web.** After an edit the other amount keeps its rule code until its own
  rule passes locally; the next prompt also covers any amount the local rules
  reject, so Create is never disabled without a prompt.
- **M-1.** The card opens only when the proposal read at least one value or the
  scope gate passes; clarifications alone no longer open it.
- **M-3.** Digits are ASCII `[0-9]` only. The $999,999.99 cap is enforced the
  same way in three places: the parser (`invalid_amount`), `CreateCaseRequest`
  (current bill above the cap is a 422; the target must already be lower), and
  the Web's local rule. The parity grid reaches the cap and one cent above it.
- **M-2** one "Nothing was created." in the failure reply; **M-4** recorded in
  the log only; **M-6** tests added (stale proposal after Restart, Edit after the
  proposal, contractions and questions, change amounts, off-topic inputs through
  the real parser outputs in `apps/web/app/components/intake-offtopic-proposals.json`,
  pinned by pytest).

## Amendment 2026-09-24 — re-review (Request Changes, I-A): more `intake-parser-v1` rules

`intake-parser-v1` was amended twice before merge. The name was not bumped
either time, because no proposal under this name has ever been merged or
recorded.

- **I-A / M-5 (bounded cost).** `_TO_AMOUNT_BEFORE` and `_FROM_TO_BEFORE` had
  adjacent `\s*…\s+` and ran on the whole preceding text for every amount, so
  their cost was quadratic (`("from 1" + " "*1300 + "$5 "*231)[:2000]` took
  about 1.7 s). They are rewritten without adjacent optional whitespace and see
  only the right-stripped last 48 characters before the amount. More than 8
  amounts make both amounts `ambiguous` without reading each one. A timing test
  asserts < 250 ms for the reviewer's worst inputs at 2000 characters.
- **Target cues.** "I'd like", "would like", "hoping", "hope for", "happy with",
  and "happy at" are target cues ("want it to be $X" and "get it down to $X"
  already were).
- **Lowering requests.** A question clause that contains a lowering verb
  (`lower`, `reduce`, `bring down`, `cut`, `get`) still reads its amounts:
  "Can you lower my phone bill from $92 to $75?" and "How can I lower my $92
  phone bill to $75?" give current $92 and target $75. A price-history verb
  still makes them ambiguous. "phone/mobile/cell bill" right after an amount
  marks it as the current bill.
- **"Actually … both".** A later clause that negates or changes something and
  names no feature casts doubt on every named feature, not only the last one,
  when its sentence says `both`, `all`, `everything`, or `actually`.
  Examples: "Actually no.", "Actually, forget it, I want to change both."
  `forget` counts as a negation.
- **Web.** The card opens when the proposal read a value, when it has any
  amount clarification other than `missing`, or when the scope gate passes.
  This means on-topic text without a phone word still gets the card. Some
  off-topic text that mentions money ("vacation for $2,000") now opens the card
  too; the root accepted that. The copy now says "must stay below/above the
  current bill/target" (no "confirmed"). A non-422 failure says "Nothing was
  created." once.
- **Documented limits (root decision, no change).**
  - An unrelated later negation ("No rush", "I can't afford it") makes the last
    named feature `ambiguous`. This fails safe.
  - "from $X to $Y" with no verb at all is read as current → target.

## Amendment 2026-09-24 — root decision: when the card opens

The second amendment opened the card whenever an amount needed clarification,
so off-topic text that mentions money opened it ("Help me plan a vacation for
$2,000", "Convert 10 euros to dollars", "Write me a poem about my $5 coffee").
Root decision: the Web opens the Draft card when any one of these holds,
otherwise the consumer gets the scope reply.

- (a) at least one proposal field has a non-null value;
- (b) the scope gate `isSupportedMobileBillIntent` passes;
- (c) there is an amount clarification other than `missing` **and** the text
  has a cue from a closed list, matched as a whole word or phrase and ignoring
  case: `bill`, `pay`, `paying`, `paid`, `monthly`, `per month`, `a month`,
  `/mo`, `carrier`, `phone`, `mobile`, `cell`, `wireless`, `data`, `hotspot`,
  `financing`.

Bare `plan` is deliberately **not** a cue (root decision, option A): it would
open the card for "Help me plan a vacation for $2,000". Phone, data, mobile
and cell plans are still caught by those words.

Outcomes, pinned by vitest on the real parser outputs in
`apps/web/app/components/intake-offtopic-proposals.json` (pinned by pytest;
the file now also holds the on-topic rows):

| Text | Result |
|---|---|
| "My bill is $92 and I'd like $75" | card, (a) |
| "My bill went up to $92 and I want $80" | card, (c) on `bill` |
| "Help me plan a vacation for $2,000" | scope reply |
| "Convert 10 euros to dollars" | scope reply |
| "Write me a poem about my $5 coffee" | scope reply |
| "What does device financing mean?" | scope reply |
| "Can I keep my hotspot?" | scope reply |
| "My plan went up to $92" | scope reply (documented limit) |

**Documented limit.** "My plan went up to $92", with no other cue, now gets the
scope reply. Its amount is `ambiguous` (price-history verb) and `plan` is not a
cue. The consumer can rephrase with "bill" or a phone word. The parser and
`intake-parser-v1` are unchanged; this is a Web-only rule.

## Amendment 2026-09-24 — focused re-review (Request Changes, I-1): fourth set of rules

Root decisions on the focused re-review. The rule set is still
`intake-parser-v1`, because nothing under that name has been merged.

- **I-1 `get`.** Bare `get` no longer makes a question a lowering request. It
  counts only as `get … down|lower|cheaper|under|below|reduced`, with at most 40
  characters between and no `than` after. `lower` followed by `than` is a
  comparative, not a request. These are ambiguous for every amount:
  - "Should I get the $92 plan? I want to pay under $80."
  - "Why did my bill get to $92?"
  - "Is $80 realistic to get?"
  - "Should I get the $92 plan?"
  - "Can I get it lower than $92?"

  "Could you get my mobile bill down to $75?" still reads $75 as the target.
- **M-1 bounded cost.**
  - `_ALL_DOUBT` and the retraction check run once per sentence, and the
    result is stored on each clause.
  - Text longer than `NORMALIZED_TEXT_MAX_LENGTH = 4000` characters after NFKC
    and lowercasing is not read. All four fields get the existing closed reason
    `missing` and no value. No new reason code was added, so the Web contract
    is unchanged.
  - The history check and both role-cue scans (the words since the previous
    amount, then the clause before the amount) see only the same 48-character
    tail, cut at a word boundary.
  - The timing table gained two of the reviewer's NFKC-expansion inputs, the
    un-expanded orphan-negation run, and one expanded input below the cap.
    Each is asserted < 250 ms; the measured numbers are in the log.
- **M-2 both role cues.** In the window the role scan uses, a current cue that
  is nearer the amount than the last target cue makes the amount ambiguous.
  Before, target-first order decided. When the target cue is the nearer one,
  or both start at the same place (`at most`), the target stands. Reading the
  rule this way is an implementer interpretation. The literal "any clause with
  both" would also make "Could you get my mobile bill down to $75?" ambiguous,
  because `bill` is a current cue, and I-1 requires that sentence to read $75.
  - Ambiguous now: "Hoping you can explain why my bill is $92", "I'm happy at
    $92, I'd rather keep it", "I'd like to lower my phone bill that is
    currently $92".
  - **Previously read as values, now ambiguous:** "My budget is $75", "I only
    want to pay $75", "would like to pay $80", "My target is $75".
- **M-3 retractions.** A sentence that is only "No", or that holds "wait, no",
  "never mind", or "scratch that", casts doubt on every feature already named.
  A retraction clause needs no negation word to count.
- **M-4 Web.** In card rule (c), `unsupported_currency` does not count as an
  amount clarification. "Which phone should I take on a euro trip?" gets the
  scope reply. The real parser output is in the fixture.
- **M-5 Web.** Every failure of the intake-proposal request shows the same
  message. This covers a 422, a network failure, any other 4xx or 5xx, and a
  200 whose body is not JSON or is not a valid proposal. The message is "I
  couldn't read that message right now. Nothing was created." and has no Case
  wording.
