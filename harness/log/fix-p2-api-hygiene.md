# Log: fix/p2-api-hygiene (R-2, B2-7, B2-9, G-3)

Spec: `harness/context/fix-p2-api-hygiene-preflight.md`. Branch
`fix/p2-api-hygiene` from `main` @ `74e2073`.

## Changes

- **R-2** `runtime/services/api/src/proxyloop_api/app.py`
  `handle_not_found` / `handle_conflict`: 404 → `{"detail": "not_found"}`,
  409 → `{"detail": <category>}` (`stale_cas` | `case_conflict`, unchanged
  `_conflict_category`), the same string shape the Temporal branch returns.
  Root decision: every 404 detail, including the Temporal branch's (was
  `"case not found"`), is the code `not_found`, since an unknown approval
  id is not a missing Case. The Web maps 404 by status only
  (`runtime-client.ts` `errorCategory`). Status codes and operation-record
  categories unchanged. New
  `_log_refusal` writes the Runtime text at INFO on `proxyloop_api.app` with
  the correlation id and category. Every `CaseConflictError` /
  `CaseNotFoundError` message in `runtime/` is a static literal (grep), so
  the log carries no request content. The Web reads only an object
  `detail.code` and otherwise maps by status, so it needs no code change.
- **B2-7** `runtime.py` `current_result`: the receipt route is used only
  when `transition.after_revision == snapshot.revision`; a replayed receipt
  the Case has moved past reports `terminal` / `current` like a plain read.
- **B2-9** `runtime.py` `_approve_serialized`: removed the dead
  `_clock_now()` in the non-pending terminal branch (the audited line). The
  `APPROVED`-branch call (`1ca982ee`, commented "keep the clock contract")
  is left as is.
- **G-3** `scripts/run_phase_04d_control_plane_profile.py`: `--check` runs
  `_check_report` against `BASELINE_SHAPE` (key tree + exact leaf types)
  and exact deterministic values (`count = 2*iterations+1`,
  `error_rate = timeout_rate = 1/count`, statuses `[200, 201, 503]`,
  categories `["model_timeout", "none"]`, records = count, profile and
  claim text), plus `p50 >= 0`, `p95 >= p50`. No timing thresholds. Failure
  prints each difference to stderr and exits 1; no `assert`.
  `docs/development.md` target description updated.

Independent review: Approve with four Minors, all applied:

- **M1** `app.py` `_conflict_category`: the Runtime's "approval expired"
  → `approval_expired` (direct mode now matches real Temporal for expiry).
- **M2** `app.py` `handle_request_validation`: replaces FastAPI's default
  422 body (which echoed `input`) with
  `{"detail": {"code": "request_invalid", "message": "request rejected"}}`;
  logs `(location, type)` pairs only. The Web already lists
  `request_invalid` and maps 422 to it; no Web change.
- **M3** `runtime.py` `current_result`: `fast_decision` is attached only
  under the same `after_revision == snapshot.revision` guard as the route.
- **M4** B2-7 tests for a replay after a later write and after an approval
  expiry. No public command can follow the approval-opening event (a
  second event is refused with "case is awaiting approval" or "case
  approval is terminal"), so the later-write test seeds one revision bump
  plus a later Fast decision through the repository.

## Red → green

| Test | Red on main | Green |
|---|---|---|
| `test_api_hygiene.py::test_conflict_and_not_found_details_are_category_only` | `'case already exists' != 'case_conflict'` | pass |
| `::test_internal_conflict_text_is_logged_not_returned` | internal text in body | pass |
| `::test_event_replay_after_completion_reports_the_snapshot_route` | `'wait_for_approval' == 'terminal'` | pass |
| `::test_repeat_decision_on_rejected_approval_reads_no_clock` | `4 == 3` clock reads | pass |
| `::test_temporal_not_found_detail_is_the_category_code` | `'case not found' != 'not_found'` | pass |
| `test_phase_04d_...::test_profile_check_compares_the_committed_baseline_without_assert` | `ImportError: _check_report` | pass |
| M1 `::test_direct_approval_after_its_deadline_is_approval_expired` | `'case_conflict' != 'approval_expired'` | pass |
| M2 `::test_request_validation_returns_a_fixed_body_and_logs_no_input` ×4 (extra field, over-long content, malformed JSON, bad path UUID) | default list body echoing `input` | pass |
| M3/M4 `::test_replay_after_a_later_write_reports_current_without_a_stale_fast` | `'fast' not in {...}` fails | pass |
| M4 `::test_replay_after_an_approval_expiry_reports_current` | already green on the B2-7 guard (regression test) | pass |

`python -O scripts/run_phase_04d_control_plane_profile.py --check` exits 0;
with a tampered `timeout_rate` under `-O` it prints
`requests.timeout_rate: expected 0.333…, got 0.0` and exits 1.

## Existing expectations changed (now intentionally generic)

- `test_phase_04a_agent_runtime.py`: `case is awaiting approval`,
  `approval is already terminal`, `case is terminal` (×2),
  `injected final CAS conflict` (×2) → `case_conflict`;
  `case snapshot revision is stale` → `stale_cas`; `case not found` →
  `not_found`.
- `test_direct_mode_command_path.py`: `REUSED` (`command id was reused for
  a different command`), `case already exists`, `approval is already
  terminal`, `clock time must advance event time` → `case_conflict`;
  `case snapshot revision is stale` (×2) → `stale_cas`; module docstring.
- `test_phase_04d_control_plane_operations.py`: stale revision →
  `stale_cas`.
- `apps/web/lib/runtime-client.test.ts`: create-409 fixture `case already
  exists` → `case_conflict` (fixture fidelity only; the Web maps by status).

## Known limits

- ~~A replayed `/events` receipt still carries `fast` from
  `state.last_fast_decision` even if a later event produced it~~ — fixed by
  review M3.
- For a stale revision, direct mode and the fake Temporal client return
  `{"detail": "stale_cas"}` while real Temporal returns `case_conflict`
  (the workflow activity classifies it); the fix belongs in
  `workflow_worker/activities.py`, out of scope.
- The M2 validation log includes field locations, which for an
  `extra_forbidden` error is the client-chosen key name (never its value).
- The `APPROVED`-branch `_clock_now()` (`runtime.py` ~1102) stays by root
  decision.

## Checks

First pass (before the `not_found` change):

- Focused pytest (7 API/runtime files): 106 passed.
- `make format-check`: pass. `make lint`: pass. `make typecheck`: pass
  (66 and 59 source files).
- `make phase04d-profile-check`: pass.
- `pnpm install --frozen-lockfile`; `make web-check`: pass (140 tests).
- `make preflight-fast`: pass.
- `make test`: runtime 1205 passed, 51 skipped; ml 397 passed, 1 skipped;
  all artifact checks passed. `PROXYLOOP_TEST_*` unset.

After the `not_found` change:

- Focused pytest (7 API/runtime files): 107 passed.
- `make format-check`, `make lint`, `make typecheck`, `make preflight-fast`:
  pass.

After merging `origin/main` @ `ff35dca` (docs only), serially, with the
shared test DB held exclusively (variables on the make command line only):

- `make postgres-check`: 27 passed.
- `make phase05a-check`: 42 passed (99 s).
- `make phase06b1-check`: 35 passed.
- `make preflight` (variables unset): pass; runtime 1206 passed, 51
  skipped; ml 397 passed, 1 skipped; Web 140 passed; artifact checks
  passed.

After review M1–M4 (DB gates not yet rerun; the DB is held elsewhere):

- Focused pytest (7 API/runtime files): 114 passed.
- `make format-check`, `make lint`, `make typecheck` (66 / 59 files),
  `make preflight-fast`: pass.
- `make web-check`: pass, 140 tests.
- `make test`: runtime 1213 passed, 51 skipped; ml 397 passed, 1 skipped;
  artifact checks passed.

Docs step: `harness/context/audit-remediation-status.md` moves R-2, B2-7,
B2-9, G-3 to the closed tables (branch name, PR pending) and records the
API-error limits in §6. `docs/architecture.md` and `docs/ui/state-matrix.md`
describe no API error body; unchanged.

After merging `origin/main` @ `d23aff9` (#80, router precedence), serially,
with the shared test DB held exclusively (variables on the make command line
only):

- `make postgres-check`: 27 passed.
- `make phase05a-check`: 42 passed (103 s).
- `make phase06b1-check`: 35 passed.
- `make preflight` (variables unset): pass; runtime 1216 passed, 51
  skipped; ml 397 passed, 1 skipped; Web 140 passed; artifact checks
  passed.
