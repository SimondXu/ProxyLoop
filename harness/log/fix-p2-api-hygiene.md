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

## Red → green

| Test | Red on main | Green |
|---|---|---|
| `test_api_hygiene.py::test_conflict_and_not_found_details_are_category_only` | `'case already exists' != 'case_conflict'` | pass |
| `::test_internal_conflict_text_is_logged_not_returned` | internal text in body | pass |
| `::test_event_replay_after_completion_reports_the_snapshot_route` | `'wait_for_approval' == 'terminal'` | pass |
| `::test_repeat_decision_on_rejected_approval_reads_no_clock` | `4 == 3` clock reads | pass |
| `::test_temporal_not_found_detail_is_the_category_code` | `'case not found' != 'not_found'` | pass |
| `test_phase_04d_...::test_profile_check_compares_the_committed_baseline_without_assert` | `ImportError: _check_report` | pass |

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

- A replayed `/events` receipt still carries `fast` from
  `state.last_fast_decision`, i.e. the latest Fast decision even if a later
  event produced it; the B2-7 guard covers `route` only.
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
