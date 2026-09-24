# Feature log: the Stage 2 Judge seam (PR-14)

Spec (frozen by the root, 2026-09-25, root answers 1–9):
`harness/context/pr14-judge-seam-preflight.md`. Build-plan item PR-14
(decisions 7, 17, 20). Branch `feat/pr14-judge-seam`: the spec commits sit on
PR-13's branch head; `origin/main` @ `37f6bab` (PR-13, #99) was merged in
before any code (`2dfdfb9`; the conflicts were PR-13's own files, and main's
side was taken because this branch had not changed them).

Non-goals, per the spec: no contract, schema, or `contracts/` change and no
`SlowWorkRequest` field (decision 20); no change to `validate_slow_result`,
`proposal_admission.py`, `scripted.py`, `router.py`, `capabilities.py`,
`repository.py`, `postgres_repository.py`, `app.py`, `config.py`,
`workflow.py`, `activities.py`, `ml/`, or any committed artifact except the
scripted split report; no env var, no `adapter_mode` change; no model Judge.

## What changed

- `agent_core/judge.py` (new; imports the stdlib, `proxyloop_contracts`, and
  `.interfaces` only). `JudgeVerdict` (`accept` | `revise`, request and result
  ids, closed codes, validated on construction), `JudgeAdapter`,
  `JudgeAdapterFailure` (allow-listed `judge_adapter_timeout`,
  `_unavailable`, `_invalid_output`), the optional
  `FeedbackReasoningSlowAdapter.reason_with_feedback(request, verdict)`,
  `JUDGE_REVISE_CODES = {"judge_premature_give_up"}` (root answer 2),
  `JUDGE_VERDICT_VERSION = "judge-verdict-v1"`, and `ScriptedJudgeAdapter`
  (`scripted / scripted_judge / rules-v1 / scripted-v1 / no-prompt`): revise
  iff the result has no capability proposal while an offer has
  `expires_at > request.created_at` and the manifest has the accept-only
  capability; accept otherwise. Exported from `proxyloop_agent_core`.
- `agent_core/coordinator.py`: `CaseCoordinator(..., judge=None)` (root answer
  6). In the Slow branch, after the admitted Slow trace, `_judged` calls the
  Judge (timed; a `JudgeAdapterFailure` is captured, anything else
  propagates), checks the verdict binds the request and result, appends one
  `judge` audit and trace, and on a binding `revise` with a feedback-capable
  Slow retries once on the same request object; the retry goes through the
  same `_admit_slow` (validation + A-3) and gets its own `slow` audit and
  trace. The retry is final and never judged; if it is rejected, or the Judge
  failed, or the verdict did not bind, the first admitted result is used. A
  Slow adapter without the protocol is not retried (root answer 3); an
  exception from the retry propagates (root answer 4). Refactor only:
  `_admit_slow` and `_slow_trace` hold the existing first-call code so the
  retry reuses it; `_model_trace`'s role literal gains `"judge"`.
  `CoordinatorOutcome` and the `advance` signature are unchanged.
- `case_runtime/runtime.py`: `ThinAgentRuntime(..., judge=None)` defaults to
  `ScriptedJudgeAdapter()`; `_coordinator()` passes `judge=self._judge`.
  Nothing else: the Runtime still consumes only `outcome.slow_result`.
- `case_runtime/turn_split.py`: accepts `judge` traces; the traces at one
  cursor parse into attempts (`S [J [S']]`, then the Fast call), an orphan
  Judge trace is refused; per turn `judge_calls` and `slow_retry`
  (`null` | `admitted` | `rejected`); per scenario `judge_calls_by_result`,
  `slow_retry_counts`, `unapplied_judge_calls_by_result`;
  `unapplied_model_calls` counts Fast and Slow only; no verdict is reported
  (root answer 7).
- `scripts/run_fast_slow_split_report.py`: `fast-slow-split-v2`,
  `judge_backend: "scripted_judge"` (checked against every Judge trace's
  `model`, as a literal; the script does not import the Judge). The changes
  are additive, so PR-9b's version of this script (`--fast-backend`, the
  local reports) should merge by keeping both sides.
- `data/evaluation/fast-slow-split-scripted.json` regenerated at v2 (below).
- Docs: `docs/architecture.md` (the Judge paragraph in Model Collaboration
  and Routing, a Safety-invariants bullet, the trace-log paragraph on the
  Judge trace `result` and typed `JudgeAdapterFailure`, the split paragraph),
  an ADR amendment in `docs/decisions/2026-08-23-fast-slow-orchestration.md`,
  `CONTEXT.md` "Judge" (root answer 9 wording, via `domain-modeling`:
  checked against the glossary; "verifier" stays the Completion Decision's
  and "approval" the Approval Request's, hence the _Avoid_ list), and the
  PR-14 row in `harness/context/audit-remediation-status.md` §0.

## Red evidence (before any production edit, on `2dfdfb9`)

- `tests/integration/test_judge_seam.py` (R1–R4 and the coordinator, pure
  and Runtime tests): collection fails with
  `ModuleNotFoundError: No module named 'proxyloop_agent_core.judge'`.
- R1 behaviour, the default Runtime's `create_case`: log roles `['slow']`
  (the spec requires `['slow', 'judge']`).
- R5 `tests/contract/test_judge_boundary.py`: `1 failed, 3 passed`
  (`test_b3_the_judge_module_depends_on_contracts_and_interfaces_only`,
  `FileNotFoundError`: there is no `judge.py`).
- R6 `test_fast_slow_split_report.py -k s4`: `5 failed` — four with
  `ValueError: a turn split needs Runtime Fast/Slow traces with pins`
  (`turn_split.py:59`), the orphan test because that is the wrong error.

## Green

- The new tests: `test_judge_seam.py` 35 items (with parametrization) and
  `test_judge_boundary.py` 4, plus the four `s4` split tests, all pass.

## The regenerated report (the one committed artifact that moves)

Why: the Runtime now appends one `judge` trace after each admitted Slow
trace, which the v1 split refused. The v1→v2 check (loads the v1 file from
`origin/main` and the new file, projects the new one onto the v1 keys
recursively):

```
v1 keys differing: ['report_fingerprint', 'schema_version']
demo_path     judge_calls_by_result {succeeded: 1}  slow_retry_counts {admitted: 0, rejected: 0}  unapplied_judge_calls_by_result {succeeded: 1}
              turns (turn, judge_calls, slow_retry): (1, 1, None), (2, 0, None)
dialogue_path judge_calls_by_result {succeeded: 3}  slow_retry_counts {admitted: 0, rejected: 0}  unapplied_judge_calls_by_result {succeeded: 0}
              turns: (1,1,None) (2,1,None) (4,0,None) (6,0,None) (8,0,None) (10,0,None) (12,1,None) (14,0,None)
```

Every v1 value is identical; the values match the spec's §7 prediction. The
v2 fingerprint is `6ce4c8ed…`, the v1 fingerprint was `5413400a…`.

## Expected test churn (each only "a `judge` trace follows each admitted Slow trace")

No approval, state, receipt, or Provider expectation changed.

- `test_persisted_claim_and_traces.py`: 11 role lists (`["slow"]` →
  `["slow", "judge"]`, `["slow", "fast"]` → `["slow", "judge", "fast"]`,
  `["slow", "slow", "fast"]` → `["slow", "judge", "slow", "judge", "fast"]`);
  the one-case append test unpacks `trace, judge` and expects both written.
- `test_slow_refresh_strategy_expiry.py`: the channel-refusal helper takes the
  refused refresh's roles: `["slow", "judge"]` for a result the coordinator
  admits and the Runtime refuses (same revision, revision regression),
  `["slow"]` for one the coordinator rejects (expired strategy, not judged);
  the direct T5 test likewise.
- `test_slow_driven_intent.py`: one unpacking (`slow, judge, _fast`), one
  role/result list, and the `offer-expired` model-call count 2 → 3.
- `test_model_trace_producer.py:607`: the role set gains `judge`.
- `test_fast_slow_split_report.py`: the repeated-create roles, the retried
  refresh fixture (now `slow, judge, fast`), `schema_version` v2 and the v2
  acceptance values.
- DB-gated, verified only in the DB lane:
  `test_phase_04c_persistent_case_store.py` `_logged_flow` roles
  `["slow", "judge", "fast"]` (this is the spec's P1: the Judge trace
  round-trips PostgreSQL) and the order test's unpacking and expected tuple.
  No gated test was added; the gated-skip pin is unchanged.

## Checks (on the stable diff)

- `make lint`: passed (ruff "All checks passed!" for runtime and ml,
  `git diff --check` clean).
- `make typecheck`: passed (mypy "no issues found" in 77 and 59 source files).
- `make test`: passed — runtime `1745 passed, 66 skipped`, ml
  `397 passed, 1 skipped`, and every `*-check` in the target current
  (including `fast-slow-split-check` on the v2 report, the r4 execution
  contract unchanged, the rescored artifact, negotiation).
- `make phase04d-profile-check`: passed (exit 0).
- `make preflight`: passed (exit 0): the same runtime and ml counts, web
  vitest `189 passed`, "Gated-skip counts match the pinned 66 per file".
- Byte identity: `git diff --stat origin/main -- contracts/ ml/ data/
  runtime/packages/contracts` shows only
  `data/evaluation/fast-slow-split-scripted.json`.
- Not run (by instruction; PR-9b holds the DB lane): `make postgres-check`,
  `make phase05a-check`, `make phase06b1-check`. Ready for DB. The DB-gated
  churn above is verified only there.
- Not run: `/security-review`, independent review (the root's).

## Known limits (root answers 4 and 5; unreachable while no product Slow implements the feedback protocol)

- An exception raised by the retry call propagates; that run's traces
  (the first Slow call and the Judge call) are lost (PR-7 limit 8).
- A retry the coordinator admits but the Runtime cannot use (no strategy on
  create; a strategy that does not advance the installed revision) fails the
  command although the first result was usable.
- The scripted Judge never revises on the default Slow, so the retry path
  runs only in tests (fake feedback-capable Slow adapters).
- PR-9b's local split reports, when merged, stay pre-Judge observed
  artifacts; `check_local_report` compares only the Fast/Slow structure keys,
  which v2 leaves unchanged.
