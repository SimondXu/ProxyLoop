# Fix: P2 API hygiene (R-2, B2-7, B2-9, G-3)

Bounded repository change under the 2026-09-22 audit-remediation standing
authorization (P2 batch 2). Branch `fix/p2-api-hygiene` from `main` @
`74e2073`. Non-goals: B2-8 (event-loop blocking), any canonical contract
change, `ml/`, `data/`, the Web (unless it parses a changed message; it
does not, see R-2).

## Defects (observed on main @ 74e2073)

- **R-2** (`harness/context/audit-remediation-status.md:262`)
  `runtime/services/api/src/proxyloop_api/app.py:222-231`: the
  `CaseNotFoundError` and `CaseConflictError` handlers return
  `{"detail": str(exc)}`, echoing Runtime/repository exception text to the
  browser (for example `"command id was reused for a different command"`,
  a test-injected `"injected final CAS conflict"`). Every other handler
  already returns a content-free detail.
- **B2-7** (`harness/code_review/repo-audit-B2.md:59`)
  `runtime.py` `current_result` takes `route` from the transition receipt
  even when the receipt is a deduplicated replay of an older command: an
  `/events` replay after completion returns `route=wait_for_approval` with a
  `complete` snapshot.
- **B2-9** (`repo-audit-B2.md:65`) `runtime.py` `_approve_serialized`, the
  non-pending terminal branch (`approval is already terminal`), calls
  `self._clock_now()` and discards the value, consuming a tick of an
  injected sequence clock.
- **G-3** (`harness/code_review/repo-audit-G.md:40`)
  `scripts/run_phase_04d_control_plane_profile.py` `--check` uses three
  bare `assert`s (disabled by `python -O`) and compares against nothing
  committed.

## Evidence checked

- Web: `apps/web/lib/runtime-client.ts` `errorCategory` reads only an
  object `detail.code`; a string `detail` falls back to the HTTP status. No
  Web code matches on detail text ("expired", "final CAS", ...). No Web
  change is needed.
- Docs/contracts: no error detail string is documented in `docs/`,
  `contracts/`, or `CONTEXT.md` (grep for each Runtime message). No
  escalation.
- Temporal failure mapping (`workflow_worker/activities.py`) is untouched.
  The API's Temporal branch already returns `{"detail": "case not found"}`
  (404) and `{"detail": "<category>"}` (409).

## Frozen design

1. **R-2.** The two handlers return a string-shaped detail like the
   Temporal branch: 404 → `{"detail": "not_found"}` (root decision: one
   snake_case code for every 404, including the Temporal branch, since
   "case not found" is wrong for an unknown approval id);
   409 → `{"detail": <category>}` where category is the unchanged
   `_conflict_category(exc)` (`stale_cas` or `case_conflict`). Status codes
   and operation-record categories are unchanged. The exception text is
   logged server-side at INFO on `proxyloop_api.app` with the request's
   correlation id and category (the allowlisted `OperationRecord` has no
   free-text field and is not widened). The fake-Temporal tests now match
   real Temporal's detail for these categories.
2. **B2-7.** `current_result` uses `transition.route` only when the receipt
   produced the current snapshot (`transition.after_revision ==
   snapshot.revision`); otherwise the route is derived from the snapshot as
   for a plain read (`terminal` / `current`).
3. **B2-9.** Delete the dead `_clock_now()` call in the non-pending
   terminal branch. The call in the `APPROVED` branch (added in `1ca982ee`
   with a "keep the clock contract" comment) is not the audited line and
   stays.
4. **G-3.** `--check` compares the fresh report with a committed shape
   baseline in the script (key tree and leaf types, fixed profile/claim
   values, and the deterministic counts: `count == 2 * iterations + 1`,
   statuses `[200, 201, 503]`, categories `["model_timeout", "none"]`,
   `operation_records == count`, `timeout_rate == error_rate == 1/count`),
   plus the existing `p50 >= 0`, `p95 >= p50`. No timing thresholds. On
   failure it prints each failure and exits 1 via `SystemExit`, not
   `assert`.

## Tests (red first)

- `tests/integration/test_api_hygiene.py` (new): R-2 (409 and 404 details
  are category-only, an injected internal message never reaches the body
  but is logged with the correlation id), B2-7 (replay after completion
  returns `route == "terminal"`), B2-9 (a repeat decision on a rejected
  approval reads the clock zero times).
- `tests/integration/test_phase_04d_control_plane_operations.py`: G-3
  `_check_report` returns named failures for a tampered report and none for
  a fresh one.
- Existing tests asserting a now-generic detail string are updated and
  listed in the log.

## Verification

Focused pytest; `make format-check lint typecheck`; `make preflight-fast`;
`make test`. DB/Temporal gates are run later, serially, at root's request.
