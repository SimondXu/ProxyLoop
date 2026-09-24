# Fix: Web P2 hygiene batch (P2 E-7, E-8, E-9/R-3, E-10, R-8)

Bounded change under `harness/context/audit-remediation-decisions.md`.
Branch `fix/p2-web-hygiene` from `origin/main` @ `5bedcce` (after #63
sticky-blocked and #66 direct-mode copy).

## Defects (audit `harness/code_review/repo-audit-E.md`), verified on `5bedcce`

- **E-7.** The working/finalizing poll (`conversation-workspace.tsx`
  poll effect) keeps reading while the event `POST` is in flight. An
  unchanged `GET` maps to `confirm` in `phaseForPayload`, so the display
  flips `Working` → `Needs input` and the Progress artifact disappears
  until the `POST` settles.
- **E-8.** `ProgressArtifact` renders two hard-coded `done` steps ("Case
  snapshot read", "Guardrails checked") that no payload field backs.
- **E-9 / R-3.** The context-rail Usage row reads
  `bill_snapshot.usage.data_gb`; the contract field is
  `UsageProfile.data_megabytes` and the #57 allow-list projection emits no
  `usage`, so the row always shows the literal "Runtime fact".
- **E-10.** `parseUsdMoney` contradicts its own prompt ("Use a value such
  as $92.00."): `$92.00.` and `$92.` are rejected, `$1,50` parses as $1.00,
  `$12345` is rejected, and `12.345 USD` parses as $345.00.
- **R-8.** The projection's `completion` is a synthetic `not_done` object
  when the Runtime has no `CompletionDecision`; undocumented.

## Frozen design

1. **E-7.** A ref records the session id of the event/approval `POST` in
   flight (cleared in that handler's `finally` and on restart). A poll read
   (`readAuthoritativeCase(..., { poll: true })`) during that command that
   maps to `confirm` accepts the payload but leaves the phase unchanged. A
   poll may still advance the phase or block (#63 sticky blocked is
   untouched: the blocked checks run before the guard).
2. **E-8.** Progress renders only: a done step "Case revision N read"
   (the accepted payload passed `hasValidTaskBrief` against the confirmed
   facts) and one active step — "Runtime decision" while working,
   "Execution pending" while finalizing (`snapshot.pending_execution`).
3. **E-9.** Project `bill_snapshot.usage = {data_megabytes}` explicitly in
   `_browser_case`; add `usage`/`data_megabytes` to the projection test's
   exact key sets; render "N MB data", else "Unavailable".
4. **E-10.** Amount grammar: one `$` or `USD` amount, comma-grouped
   (`1,500`) or plain digits, at most two decimals; a trailing sentence
   period is allowed; a following digit, letter, comma, or `.digit`
   rejects; the `USD` form may not start inside a number. Prompt copy is
   unchanged and now agrees with the parser.
5. **R-8.** Document only (`docs/ui/state-matrix.md` projection note).

No runtime-package change; the one service change is the `runtime/services/api` `app.py` browser projection (E-9). No visual redesign.
